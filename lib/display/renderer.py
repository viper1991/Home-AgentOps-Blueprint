"""墨水屏渲染器。Layout + Widget 架构。

Layout 定义屏幕几何分区:
  Top 70% (Y 0~335):   均分为 3 列，每列一个 Widget
  Bottom 30% (Y 336~479): 一个 Widget 横跨全宽

Widget 自适应: 根据传入数据的行数 + 最长文本宽度，自动计算字号和行高，
确保所有内容完整显示，不截断不换行。

局部刷新时 Layout 复用上次 PIL Image，只擦除+重绘 data 中存在的 Widget。
"""

import os
import logging
from abc import ABC, abstractmethod
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

WIDTH  = 800
HEIGHT = 480

# ── 布局常量 ──
TOP_RATIO     = 0.65
MID_RATIO     = 0.30
BOTTOM_RATIO  = 0.05
TOP_H         = int(HEIGHT * TOP_RATIO)     # 312
MID_H         = int(HEIGHT * MID_RATIO)     # 144
MID_Y         = TOP_H                       # 312 (summary 区域起始)
BOTTOM_Y      = TOP_H + MID_H               # 456 (底部状态栏起始)
BOTTOM_H      = HEIGHT - BOTTOM_Y           # 24
CONTENT_TOP   = 35                          # 内容起始 Y（避开标题栏）
CHROME_H      = 28                          # 列标题栏高度
COL_W         = [267, 267, 266]             # 三列宽度
COL_X         = [0, 267, 534]               # 三列起始 X
_BLACK = 0
_WHITE = 255

# 自适应约束
_FONT_SZ_MIN  = 10
_FONT_SZ_MAX  = 80


# ── 字体查找回退链 ──

_WINDOWS_FONT_DIRS = [
    r'C:\Windows\Fonts',
    r'C:\WINNT\Fonts',
]

_COMMON_CJK_FONTS = [
    'msyh.ttc',
    'simhei.ttf',
    'simsun.ttc',
    'NotoSansSC-VF.ttf',
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
]


def _resolve_font_path(font_dir: str, preferred_name: str) -> str | None:
    candidates = []
    candidates.append(os.path.join(font_dir, preferred_name))
    if os.path.isdir(font_dir):
        for f in sorted(os.listdir(font_dir)):
            if f.lower().endswith(('.ttf', '.ttc', '.otf')):
                candidates.append(os.path.join(font_dir, f))
                break
    candidates.extend([
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ])
    for win_dir in _WINDOWS_FONT_DIRS:
        for cjk in _COMMON_CJK_FONTS:
            candidates.append(cjk if os.path.isabs(cjk) else os.path.join(win_dir, cjk))
    seen = set()
    for fp in candidates:
        if fp in seen:
            continue
        seen.add(fp)
        if os.path.exists(fp):
            return fp
    return None


# ══════════════════════════════════════════════════════════════════
#  Widget 基类
# ══════════════════════════════════════════════════════════════════

class Widget(ABC):
    """Widget 抽象基类。bounds = (x, y, w, h) 在画布上的绝对位置和尺寸。"""

    def __init__(self, widget_id: str, bounds: tuple[int, int, int, int], padding: int = 8):
        self.widget_id = widget_id
        self.bounds = bounds
        self.padding = padding
        self._font_path: str | None = None
        self._font_cache: dict[int, ImageFont] = {}

    def set_font_path(self, path: str | None):
        self._font_path = path
        self._font_cache = {}

    def _make_font(self, size: int) -> ImageFont:
        if size not in self._font_cache:
            if self._font_path:
                try:
                    self._font_cache[size] = ImageFont.truetype(self._font_path, size)
                except Exception:
                    self._font_cache[size] = ImageFont.load_default()
            else:
                self._font_cache[size] = ImageFont.load_default()
        return self._font_cache[size]

    def clear(self, draw: ImageDraw):
        x, y, w, h = self.bounds
        draw.rectangle((x, y, x + w - 1, y + h - 1), fill=_WHITE)

    @abstractmethod
    def render(self, draw: ImageDraw, data) -> None:
        ...


# ══════════════════════════════════════════════════════════════════
#  TableWidget — 两列表格 (名称 | 数值) ，自适应行高 + 字号
# ══════════════════════════════════════════════════════════════════

class TableWidget(Widget):
    """两列表格：左列 label，右列 value + trend。自适应填满区域，完整显示所有文本。

    自动合并同 label 行：温湿度同 label 时合并为 "26°C / 54%"
    """

    def __init__(
        self,
        widget_id: str,
        bounds: tuple[int, int, int, int],
        col_ratios: tuple[float, float] = (0.45, 0.55),
        padding: int = 8,
    ):
        super().__init__(widget_id, bounds, padding)
        self.col_ratios = col_ratios

    @staticmethod
    def _merge_same_label(data: list) -> list:
        """合并同 label 的连续行（温湿度配对），返回新列表。"""
        if not data:
            return []
        merged = []
        i = 0
        while i < len(data):
            item = data[i]
            label = item.get('label', '')
            # 检查下一行是否同 label
            if i + 1 < len(data) and data[i + 1].get('label') == label:
                # 合并两行: value1 / value2
                v1 = item.get('value', '')
                v2 = data[i + 1].get('value', '')
                merged.append({
                    'label': label,
                    'value': f'{v1} / {v2}',
                    'trend': item.get('trend', ''),
                    'remark': item.get('remark', ''),
                    'detail': item.get('detail', '') or data[i + 1].get('detail', ''),
                })
                i += 2
            else:
                merged.append(item)
                i += 1
        return merged

    def _count_rows(self, data: list) -> int:
        merged = self._merge_same_label(data)
        n = 0
        for item in merged or []:
            n += 1
            if item.get('detail'):
                n += 1
        return max(n, 1)

    def _find_font_size(self, data: list, col1_w: int, col2_w: int) -> int:
        """二分查找能容纳所有文本的最大字号。"""
        merged = self._merge_same_label(data)
        if not merged:
            return _FONT_SZ_MIN

        # 纵向约束
        n_rows = self._count_rows(merged)
        avail_h = self.bounds[3] - self.padding * 2
        vert_max = int((avail_h // n_rows) * 0.68)

        lo, hi = _FONT_SZ_MIN, min(_FONT_SZ_MAX, vert_max)
        best = _FONT_SZ_MIN

        while lo <= hi:
            mid = (lo + hi) // 2
            font = self._make_font(mid)
            ok = True
            for item in merged:
                if font.getlength(item.get('label', '')) > col1_w:
                    ok = False; break
                if font.getlength(item.get('value', '')) > col2_w:
                    ok = False; break
                d = item.get('detail', '')
                if d and font.getlength(d) > col1_w + col2_w - 6:
                    ok = False; break
            if ok:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def render(self, draw: ImageDraw, data) -> None:
        if not data:
            return

        merged = self._merge_same_label(data)

        x, y0, w, _h = self.bounds
        pad = self.padding
        n_rows = self._count_rows(merged)
        row_h = (self.bounds[3] - pad * 2) // n_rows

        col1_w = int(w * self.col_ratios[0]) - pad
        col2_w = w - int(w * self.col_ratios[0]) - pad
        col2_x = x + int(w * self.col_ratios[0])

        font_sz = self._find_font_size(merged, col1_w, col2_w)
        font = self._make_font(font_sz)
        y = y0 + pad

        for item in merged:
            draw.text((x + pad, y), item.get('label', ''),
                      font=font, fill=_BLACK)
            draw.text((col2_x, y), item.get('value', ''),
                      font=font, fill=_BLACK)
            y += row_h

            detail = item.get('detail', '')
            if detail:
                draw.text((x + pad + 8, y), detail,
                          font=font, fill=_BLACK)
                y += row_h


# ══════════════════════════════════════════════════════════════════
#  ListWidget — 逐行列表，自适应行高 + 字号
# ══════════════════════════════════════════════════════════════════

class ListWidget(Widget):
    """逐行列表。数据填满区域，完整显示所有文本，不自动换行。"""

    def __init__(
        self,
        widget_id: str,
        bounds: tuple[int, int, int, int],
        padding: int = 8,
    ):
        super().__init__(widget_id, bounds, padding)

    def _count_rows(self, data: list) -> int:
        return max(len(data or []), 1)

    def _find_font_size(self, data: list, avail_w: int) -> int:
        """二分查找能容纳所有行的最大字号。"""
        if not data:
            return _FONT_SZ_MIN

        n_rows = self._count_rows(data)
        avail_h = self.bounds[3] - self.padding * 2
        vert_max = int((avail_h // n_rows) * 0.68)

        # 收集所有需要显示的文本
        texts = []
        for item in data:
            if isinstance(item, dict):
                texts.append(f"{item.get('time', '')} {item.get('text', '')}")
            else:
                texts.append(str(item))

        lo, hi = _FONT_SZ_MIN, min(_FONT_SZ_MAX, vert_max)
        best = _FONT_SZ_MIN

        while lo <= hi:
            mid = (lo + hi) // 2
            font = self._make_font(mid)
            ok = all(font.getlength(t) <= avail_w for t in texts)
            if ok:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def render(self, draw: ImageDraw, data) -> None:
        if not data:
            return

        x, y0, w, _h = self.bounds
        pad = self.padding
        avail_w = w - pad * 2
        n_rows = self._count_rows(data)
        row_h = (self.bounds[3] - pad * 2) // n_rows

        font_sz = self._find_font_size(data, avail_w)
        font = self._make_font(font_sz)
        y = y0 + pad

        for item in data:
            if isinstance(item, dict):
                line = f"{item.get('time', '')} {item.get('text', '')}"
            else:
                line = str(item)
            draw.text((x + pad, y), line, font=font, fill=_BLACK)
            y += row_h


# ══════════════════════════════════════════════════════════════════
#  StatusBarWidget — 单行状态栏，自适应居中
# ══════════════════════════════════════════════════════════════════

class StatusBarWidget(Widget):
    """底部状态栏：单行文本，自动缩放字号填满区域。"""

    def _find_font_size(self, text: str, avail_w: int, avail_h: int) -> int:
        if not text:
            return _FONT_SZ_MIN
        lo, hi = _FONT_SZ_MIN, min(_FONT_SZ_MAX, int(avail_h * 0.75))
        best = _FONT_SZ_MIN
        while lo <= hi:
            mid = (lo + hi) // 2
            font = self._make_font(mid)
            if font.getlength(text) <= avail_w:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def render(self, draw: ImageDraw, data) -> None:
        if not data:
            return
        text = data.get('text', '') if isinstance(data, dict) else str(data)
        if not text:
            return

        x, y0, w, h = self.bounds
        pad = self.padding
        avail_w = w - pad * 2
        avail_h = h - pad * 2

        font_sz = self._find_font_size(text, avail_w, avail_h)
        font = self._make_font(font_sz)
        tw = font.getlength(text)
        th = font_sz
        draw.text(
            (x + (w - tw) // 2, y0 + (h - th) // 2),
            text, font=font, fill=_BLACK,
        )


# ══════════════════════════════════════════════════════════════════
#  Layout — 布局管理器
# ══════════════════════════════════════════════════════════════════

class Layout:
    """屏幕布局管理器。持有 Widget 实例，提供全刷和局部刷渲染路径。"""

    def __init__(self):
        self.widgets: dict[str, Widget] = {}
        self._last_image: Image.Image | None = None
        self._last_data: dict | None = None
        self._title_font = None
        self._fonts_loaded = False
        self._font_dir = None
        self._cfg = None

    def configure(self, font_dir: str, cfg):
        self._font_dir = font_dir
        self._cfg = cfg
        self._fonts_loaded = False

    def register_widget(self, widget: Widget):
        self.widgets[widget.widget_id] = widget

    def build_default_layout(self):
        # 顶部 60%：三列（传感器 / 网络 / 事件）
        col_h = TOP_H - CONTENT_TOP
        self.register_widget(TableWidget(
            'sensor_panel',
            (COL_X[0], CONTENT_TOP, COL_W[0], col_h),
        ))
        self.register_widget(TableWidget(
            'network_panel',
            (COL_X[1], CONTENT_TOP, COL_W[1], col_h),
        ))
        self.register_widget(ListWidget(
            'events_panel',
            (COL_X[2], CONTENT_TOP, COL_W[2], col_h),
        ))
        # 中部 30%：summary（全宽）
        self.register_widget(ListWidget(
            'summary',
            (0, MID_Y + 8, WIDTH, MID_H - 12),
        ))
        # 底部 10%：刷新时间状态栏（全宽）
        self.register_widget(StatusBarWidget(
            'refresh_info',
            (0, BOTTOM_Y + 4, WIDTH, BOTTOM_H - 6),
            padding=6,
        ))
        return self

    def _load_fonts(self):
        if self._fonts_loaded:
            return
        font_name = getattr(self._cfg.font, 'name', 'SourceHanSansSC-Regular.otf')
        font_path = _resolve_font_path(self._font_dir, font_name)

        if font_path:
            try:
                self._title_font = ImageFont.truetype(
                    font_path, self._cfg.font.title_size or 22
                )
                logger.info("Loaded font: %s (title=%d)",
                            font_path, self._cfg.font.title_size or 22)
            except Exception as e:
                logger.warning("Title font load failed: %s", e)
                self._title_font = ImageFont.load_default()
        else:
            logger.warning("No CJK font found, using PIL default")
            self._title_font = ImageFont.load_default()

        for widget in self.widgets.values():
            widget.set_font_path(font_path)

        self._fonts_loaded = True

    def _draw_chrome(self, draw: ImageDraw):
        labels = getattr(self._cfg.layout, 'column_labels',
                         ['传感器', '网络', '事件'])
        for i, label in enumerate(labels):
            draw.text((COL_X[i] + 10, 6), label,
                      font=self._title_font, fill=_BLACK)
            draw.line(
                (COL_X[i] + 10, CHROME_H - 2,
                 COL_X[i] + COL_W[i] - 10, CHROME_H - 2),
                fill=_BLACK,
            )
        for x in (COL_X[1], COL_X[2]):
            draw.line((x, 0, x, TOP_H), fill=_BLACK)
        # 顶部区域下边界
        draw.line((0, TOP_H, WIDTH, TOP_H), fill=_BLACK)
        # summary 下边界
        draw.line((0, MID_Y + MID_H, WIDTH, MID_Y + MID_H), fill=_BLACK)

    def render_full(self, data: dict) -> Image.Image:
        self._load_fonts()
        img = Image.new('1', (WIDTH, HEIGHT), _WHITE)
        draw = ImageDraw.Draw(img)
        self._draw_chrome(draw)
        for widget_id, widget in self.widgets.items():
            wdata = data.get(widget_id)
            if wdata is not None:
                widget.render(draw, wdata)
        self._last_image = img
        self._last_data = data
        return img

    def render_partial(self, data: dict) -> Image.Image:
        self._load_fonts()
        if self._last_image is None:
            return self.render_full(data)
        img = self._last_image.copy()
        draw = ImageDraw.Draw(img)
        for widget_id, wdata in data.items():
            widget = self.widgets.get(widget_id)
            if widget is None:
                continue
            widget.clear(draw)
            widget.render(draw, wdata)
        self._draw_chrome(draw)

        combined = dict(self._last_data or {})
        combined.update(data)
        self._last_image = img
        self._last_data = combined
        return img

    def idle_image(self) -> Image.Image:
        self._load_fonts()
        img = Image.new('1', (WIDTH, HEIGHT), _WHITE)
        draw = ImageDraw.Draw(img)
        draw.rectangle((16, 16, WIDTH - 16, HEIGHT - 16), outline=_BLACK, width=2)
        text = "家庭信息仪表盘"
        draw.text(((WIDTH - self._title_font.getlength(text)) / 2, 40),
                  text, font=self._title_font, fill=_BLACK)
        text = "等待显示命令"
        draw.text(((WIDTH - self._title_font.getlength(text)) / 2,
                   (HEIGHT - 60) / 2),
                  text, font=self._title_font, fill=_BLACK)
        text = "Display Server running..."
        draw.text(((WIDTH - self._title_font.getlength(text)) / 2,
                   HEIGHT - 70),
                  text, font=self._title_font, fill=_BLACK)
        return img


def create_layout(font_dir: str, cfg) -> Layout:
    layout = Layout()
    layout.configure(font_dir, cfg)
    layout.build_default_layout()
    return layout
