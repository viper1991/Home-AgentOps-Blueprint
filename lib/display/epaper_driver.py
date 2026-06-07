"""墨水屏硬件驱动封装。

封装 Waveshare 官方 epd4in26 库，提供统一的初始化、全刷、局部刷、清屏、休眠接口。
自动定位 vendor/waveshare_epd 下的官方库并导入。
"""

import os
import sys
import logging

logger = logging.getLogger(__name__)


# ── 定位官方 Waveshare 库 ──

def _find_waveshare_lib() -> str | None:
    """在项目目录中查找 Waveshare 官方库路径。"""
    # 从当前文件位置向上找项目根
    here = os.path.dirname(os.path.abspath(__file__))          # lib/display/
    lib_dir = os.path.dirname(here)                            # lib/
    project = os.path.dirname(lib_dir)                         # hab/

    candidates = [
        os.path.join(project, 'vendor', 'waveshare_epd'),
    ]
    for c in candidates:
        if os.path.isdir(c) and os.path.isfile(os.path.join(c, '__init__.py')):
            return c
    return None


_waveshare_path = _find_waveshare_lib()
if _waveshare_path:
    _parent = os.path.dirname(_waveshare_path)
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    logger.info("Waveshare lib path: %s", _waveshare_path)

_import_error = None
_epd4in26 = None

# 懒加载: 首次实例化 EPaperDriver 时才真正导入 waveshare 库。
# 避免在 module-level 就初始化 GPIO（树莓派上可能因冲突崩溃）。


class EPaperError(Exception):
    """墨水屏操作异常。"""


class MockEPD:
    """用于非树莓派环境的模拟驱动（调试用）。"""
    width = 800
    height = 480

    def init(self):
        logger.info("[MOCK] epd.init()")

    def init_Fast(self):
        logger.info("[MOCK] epd.init_Fast()")

    def Clear(self):
        logger.info("[MOCK] epd.Clear()")

    def display(self, buf):
        logger.info("[MOCK] epd.display(%d bytes)", len(buf))

    def display_Fast(self, buf):
        logger.info("[MOCK] epd.display_Fast(%d bytes)", len(buf))

    def display_Partial(self, buf):
        logger.info("[MOCK] epd.display_Partial(%d bytes)", len(buf))

    def display_Base(self, buf):
        logger.info("[MOCK] epd.display_Base(%d bytes)", len(buf))

    def getbuffer(self, image):
        logger.info("[MOCK] epd.getbuffer(%s)", image.size)
        return [0xFF] * (int(self.width / 8) * self.height)

    def sleep(self):
        logger.info("[MOCK] epd.sleep()")


class EPaperDriver:
    """墨水屏驱动封装。

    在树莓派上使用真实的 Waveshare 库，在其他环境使用 Mock。
    """

    def __init__(self, epaper_cfg=None):
        """初始化驱动。

        Args:
            epaper_cfg: epaper 配置节（含 model / width / height 等，仅用于日志）。
        """
        self._model = getattr(epaper_cfg, 'model', '4in26') if epaper_cfg else '4in26'
        self._initialized = False

        # 默认尺寸（从配置或 fallback）
        self.width = getattr(epaper_cfg, 'width', 800) if epaper_cfg else 800
        self.height = getattr(epaper_cfg, 'height', 480) if epaper_cfg else 480

        # 懒加载 waveshare 库（避免 module-level GPIO 初始化）
        real_epd = None
        if _epd4in26 is None:
            real_epd = self._try_import_waveshare()
        else:
            try:
                real_epd = _epd4in26.EPD()
            except Exception as e:
                logger.warning("Waveshare EPD constructor failed: %s", e)

        if real_epd is not None:
            self._epd = real_epd
            # 从实例获取实际尺寸（某些 Waveshare 型号 EPD() 后就有 width/height）
            self.width = getattr(real_epd, 'width', self.width)
            self.height = getattr(real_epd, 'height', self.height)
        else:
            self._epd = MockEPD()

    @staticmethod
    def _try_import_waveshare():
        """尝试导入 waveshare 库，失败返回 None。"""
        global _epd4in26, _import_error
        try:
            from waveshare_epd import epd4in26 as ws
            _epd4in26 = ws
            _import_error = None
            logger.info("Waveshare epd4in26 loaded successfully")
            return ws.EPD()
        except Exception as e:
            _import_error = e
            _epd4in26 = None
            logger.warning("Using MOCK EPD driver (waveshare unavailable: %s)", e)
            return None

    def init(self):
        """全刷初始化 (~4s)。"""
        logger.info("EPD init (full)...")
        self._epd.init()
        self._initialized = True
        logger.info("EPD init done")

    def init_fast(self):
        """快速初始化 (~1.5s)。"""
        logger.info("EPD init (fast)...")
        self._epd.init_Fast()
        self._initialized = True
        logger.info("EPD init fast done")

    def display(self, image):
        """全刷显示（完整波形，有闪烁）。"""
        buf = self._dither_if_needed(self._epd.getbuffer(image))
        self._epd.display(buf)

    def display_fast(self, image):
        """快速全刷。"""
        buf = self._dither_if_needed(self._epd.getbuffer(image))
        self._epd.display_Fast(buf)

    def display_partial(self, image):
        """局部刷新（简化波形，无闪烁）。"""
        buf = self._dither_if_needed(self._epd.getbuffer(image))
        self._epd.display_Partial(buf)

    def display_base(self, image):
        """基画写入（存两份 RAM，为后续局部刷优化）。"""
        buf = self._dither_if_needed(self._epd.getbuffer(image))
        self._epd.display_Base(buf)

    def clear(self):
        """清屏。"""
        self._epd.init()
        self._epd.Clear()

    def sleep(self):
        """深度休眠。"""
        self._epd.sleep()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @staticmethod
    def _dither_if_needed(buf):
        """可选：对位图数据做抖动处理（目前透传）。"""
        return buf
