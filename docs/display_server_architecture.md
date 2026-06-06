# Display Server — 墨水屏显示守护进程

## 概述

`display_server.py` 是一个常驻后台的 TCP socket 守护进程，**唯一一个直接操作 GPIO 驱动墨水屏的进程**。
它通过 `localhost:5150` 接收 JSON 指令，将 `final_output` 渲染为 800×480 位图后推送到 Waveshare 4.26inch e-Paper。

其他进程（`refresh_heavyweight.py`、`refresh_lightweight.py`）通过 `lib/display/protocol.py` 的 `DisplayClient` 与其通信，自身不接触硬件。

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│                    display_server.py                          │
│                                                              │
│  socket bind(127.0.0.1:5150)                                 │
│       │                                                      │
│       ▼                                                      │
│  ┌─────────┐  render cmd  ┌──────────┐  PIL Image  ┌──────┐ │
│  │  accept │─────────────▶│ renderer │────────────▶│epaper│ │
│  │  loop   │              │ .py      │              │driver│ │
│  └─────────┘              └──────────┘              └──┬───┘ │
│       │                                                │    │
│       ▼                                                ▼    │
│  ┌─────────┐                                      ┌──────┐ │
│  │ 其他 cmd │                                      │ GPIO │ │
│  │ clear/  │                                      │ SPI  │ │
│  │ sleep/  │                                      │→墨水屏│ │
│  │ status  │                                      └──────┘ │
│  └─────────┘                                                │
└──────────────────────────────────────────────────────────────┘
```

## 刷新模式

墨水屏支持两种刷新模式，由 `render` 指令中的 `mode` 字段指定：

| 模式 | cmd.mode | 调用链路 | 耗时 | 视觉效果 | 用途 |
|------|----------|---------|------|---------|------|
| **全刷 (Full)** | `"full"` | `init()` → `display()` → `sleep()` | ~4秒 | 全局闪烁一次 | 重量级、首次初始化后 |
| **局部刷 (Partial)** | `"partial"` | `display_Partial()` | ~0.5秒 | 无闪烁，过渡平滑 | 轻量级、数值更新 |

### 刷新调用时序

```
全刷:
  epd.init()               ← 全刷初始化 (reset + registers + LUT)
  buf = epd.getbuffer(img) ← PIL → 48000字节位图
  epd.display(buf)         ← 发送数据到RAM + 触发全刷波形
  epd.sleep()              ← 进入深度睡眠

局部刷:
  img = update_existing_image(img, new_values)  ← 在原图上画新数值，不再重新生成整个布局
  buf = epd.getbuffer(img)
  epd.display_Partial(buf) ← 内部 reset + 设寄存器 + 发数据 + 触发局部波形
```

### 局部刷的实现原理

`display_Partial()` 与全刷的核心区别在于**驱动波形 (LUT)**：

- **全刷**需要完整的波形序列（擦除→拉黑→拉白→稳定），每次约 4 秒，屏幕有明显闪烁
- **局部刷**使用简化的波形序列（跳过擦除阶段，只做黑白翻转），约 0.5 秒，过渡平滑
- 但局部刷在长时间多次使用后可能产生**残影累积**——所以需要定期用全刷复位

**建议的刷新策略**：
- 每小时的重量级刷新使用 `full` 模式，彻底清除残影
- 中间的轻量级刷新使用 `partial` 模式，仅更新数值

---

## Widget 系统

### 设计理念

渲染器采用 **Layout + Widget** 架构。Layout 定义屏幕的几何分区，每个分区托管一个 Widget。Widget 是独立的渲染单元，负责在指定区域内绘制特定类型的数据。

这种设计带来三个好处：
1. **局部刷新粒度**：轻量级刷新时只需重绘变化的 Widget，而非整个屏幕
2. **可组合性**：未来新增数据类型只需实现新 Widget，插入 Layout 即可
3. **独立测试**：每个 Widget 可脱离整体布局单独调试

### Layout 定义

```
┌──────────────────────────────────────────────────────────┐
│  Layout (800×480)                                         │
│  ┌────────────────┬────────────────┬────────────────┐    │
│  │  sensor_panel  │ network_panel  │  events_panel  │    │
│  │  TableWidget   │ TableWidget    │  ListWidget    │    │
│  │  (0,0)-(266,335)│(267,0)-(533,335)│(534,0)-(799,335)│  │
│  ├────────────────┴────────────────┴────────────────┤    │
│  │  summary                                           │    │
│  │  ListWidget                                        │    │
│  │  (0,336)-(799,479)                                 │    │
│  └────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

- **Top 区域** (70%, Y: 0–335)：均分为 3 列 (266/267/266 px)，每列一个 Widget
- **Bottom 区域** (30%, Y: 336–479)：一个 Widget 横跨全宽
- 列间竖线位于 X=267 和 X=534，上/下区域分隔线位于 Y=336

### Widget 类型

#### 1. TableWidget — 表格组件

用于显示 **键值对** 数据。布局为两列：名称列 + 数值列。

```
┌──────────────────────────────┐
│  室外温度        28°C  ↑     │  ← 每行: [label] [value] [trend]
│  室外湿度        65%   →     │
│  客厅温度        26°C  ↑     │
│  主卧空调    制冷 24°C       │
│  大门门锁        已锁        │
└──────────────────────────────┘
```

**配置项**：
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `col_ratios` | `[0.55, 0.45]` | 名称列与数值列的宽度比例 |
| `row_height` | 22 | 每行高度 (px) |
| `font` | body_font | 使用的字体 |
| `padding` | 10 | 内边距 (px) |
| `trend_width` | 14 | 趋势符号宽度 (px) |

**数据格式** (对应 `final_output.sensor_panel` / `network_panel`)：
```json
[
  {"label": "室外温度", "value": "28°C", "trend": "↑", "remark": "较2h前+2°C"},
  {"label": "WAN", "value": "在线 12ms", "status": "ok", "detail": "↓3.2M ↑1.1M"}
]
```

**渲染逻辑**：
1. 从 `y = bounds.top + padding` 开始逐行绘制
2. 每行：`label` 左对齐在名称列，`value` 在数值列，`trend` 右对齐
3. 如有 `detail` 字段，另起一行缩进显示（网络面板专用）
4. 超出 Widget 底部的行自动截断
5. 文本超出列宽自动截断并加 `…`

#### 2. ListWidget — 列表组件

用于显示 **逐行文本** 数据。每行一个条目，无分列。

```
┌──────────────────────────────┐
│  14:52  大门门锁开→关        │  ← 每行: [time] [text]
│  14:30  主卧空调已关闭       │
│  13:15  客厅有人移动         │
└──────────────────────────────┘
```

**配置项**：
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `row_height` | 22 | 每行高度 (px) |
| `font` | body_font | 使用的字体 |
| `padding` | 10 | 内边距 (px) |
| `max_rows` | 0 (不限) | 最大显示行数 |

**数据格式**：

事件模式 (对应 `final_output.events_panel`)：
```json
[
  {"time": "14:52", "text": "大门门锁开→关", "level": "info"}
]
```

摘要模式 (对应 `final_output.summary_line1` / `summary_line2`)：
```json
["室外28°C室内均温25.8°C，全屋正常。", "3台AP在线23设备，功耗1.2kW。"]
```

**渲染逻辑**：
1. 从 `y = bounds.top + padding` 开始逐行绘制
2. 事件模式：绘制 `"time text"` 格式
3. 摘要模式：直接绘制字符串
4. 超出 Widget 底部的行自动截断
5. 文本超出 Widget 宽度自动截断并加 `…`

### Widget 与 final_output 的映射

| widget_id | Widget 类型 | 数据来源 | 位置 |
|-----------|------------|---------|------|
| `sensor_panel` | TableWidget | `data.sensor_panel[]` | 左上列 (0,0)-(266,335) |
| `network_panel` | TableWidget | `data.network_panel[]` | 中上列 (267,0)-(533,335) |
| `events_panel` | ListWidget | `data.events_panel[]` | 右上列 (534,0)-(799,335) |
| `summary` | ListWidget | `[data.summary_line1, data.summary_line2]` | 底部 (0,336)-(799,479) |

### Widget 局部刷新流程

```
轻量级触发 → 只有 sensor_panel + events_panel 数据变化
                    │
                    ▼
1. 取上次渲染的 PIL Image（Renderer 内部缓存）
2. 对每个变化的 widget:
   ├─ widget.clear(draw)    ← 用白色矩形擦除 Widget 区域
   └─ widget.render(draw, data[widget_id])  ← 重绘新数据
3. epd.display_Partial(buf) ← 局部波形，无闪烁
```

**关键约束**：
- 局部刷新时 **不清除未变化的 Widget 区域**，保留旧图像内容
- 必须用 `display_Partial()` 发送完整 800×480 帧缓冲——但未变化的像素与上次相同，局部波形不会让它们闪烁
- 每个 Widget 的 `clear()` 只擦除自己的 `bounds` 区域
- Renderer 内部维护 `_last_image` 和 `_last_data`，用于局部刷新时重建

---

## 与官方 Waveshare 库的关系

`display_server.py` 直接使用官方的 Waveshare 驱动库 `epd4in26.py`。

### 库位置

项目根目录下包含了完整的官方代码：

```
E-Paper_code/
└── RaspberryPi_JetsonNano/
    └── python/
        ├── lib/waveshare_epd/epd4in26.py     ← 4.26" 驱动
        ├── lib/waveshare_epd/epdconfig.py     ← GPIO/SPI 底层
        └── examples/epd_4in26_test.py          ← 官方示例
```

`display_server.py` 通过以下方式引用官方库 (`lib/display/epaper_driver.py`)：

```python
import sys
sys.path.append('/home/pi/hab/vendor/waveshare_epd')
from waveshare_epd import epd4in26
```

### 参考的官方 API

| EPD 方法 | 说明 | 在 display_server 中的使用 |
|----------|------|--------------------------|
| `init()` | 全刷初始化 | `render(full)` 第一步 |
| `init_Fast()` | 快速初始化 (~1.5s) | 备选，暂不使用 |
| `init_4GRAY()` | 4级灰度模式 | 可选灰度渲染 |
| `display(buf)` | 全刷，触发完整波形 | `render(full)` 核心 |
| `display_Fast(buf)` | 快速全刷 | 备选 |
| `display_Partial(buf)` | 局部刷，触发局部波形 | `render(partial)` 核心 |
| `display_Base(buf)` | 写入两份 RAM 做基画 | 适合基画+局部刷组合 |
| `getbuffer(image)` | PIL 图像 → 48000 字节位图 | 渲染最后一步 |
| `Clear()` | 清屏 | `clear` 指令 |
| `sleep()` | 深度睡眠，省电 | `render(full)` 最后一步 + `sleep` 指令 |

> **为什么不用 `display_Base` + 后续局部刷？** `display_Base` 将图像写入两个 RAM 区域 (0x24 和 0x26)，后续局部刷新可以利用基画做差异。但这对我们的场景收益有限，因为每次轻量级刷新渲染的是全新图像（数值变了），不是增量差异。保持流程简单：每次 `display_Partial` 渲染完整的新图像使用局部波形。

---

## Socket 协议

### 通信格式

```
TCP localhost:5150, JSON 消息, 单次请求-响应, 无长连接
```

### DisplayClient 封装

刷新脚本通过 `lib/display/protocol.py` 中的 `DisplayClient` 发送指令：

```python
from lib.display.protocol import DisplayClient

client = DisplayClient()
client.render(final_output, mode="full")      # 全刷（重量级）
client.render(updated_output, mode="partial") # 局部刷（轻量级）
client.clear()
client.sleep()
client.status()
```

### 指令/响应

#### `render` — 渲染并显示

请求：
```json
{
  "cmd": "render",
  "mode": "full",
  "data": {
    "sensor_panel": [
      {"entity_id": "sensor.shi_wai_wendu", "label": "室外温度", "value": "28°C", "trend": "↑", "remark": ""}
    ],
    "network_panel": [
      {"source": "wan_status", "label": "WAN", "value": "在线 12ms", "status": "ok", "detail": "↓3.2M ↑1.1M"}
    ],
    "events_panel": [
      {"time": "14:52", "text": "大门门锁开→关", "level": "info"}
    ],
    "summary": [
      "室外28°C室内均温25.8°C，全屋正常。",
      "3台AP在线23设备，功耗1.2kW。书房湿度65%偏高建议通风。"
    ]
  }
}
```

`mode` 字段：
- `"full"` — 全刷 (~4s)。Layout 创建新画布，渲染所有 Widget + Chrome。适用于重量级刷新。
- `"partial"` — 局部刷 (~0.5s)。Layout 复用上次图像，**仅擦除+重绘 `data` 中存在的 Widget**。适用于轻量级刷新。

**`data` 字段的 key 即 widget_id**，与 Layout 中注册的 Widget 一一对应：

| data key | Widget | 局部刷时 |
|----------|--------|---------|
| `sensor_panel` | TableWidget (左上列) | 仅在 data 中存在时才重绘 |
| `network_panel` | TableWidget (中上列) | 仅在 data 中存在时才重绘 |
| `events_panel` | ListWidget (右上列) | 仅在 data 中存在时才重绘 |
| `summary` | ListWidget (底部) | 仅在 data 中存在时才重绘 |

**局部刷示例** — 只更新传感器数值和事件，网络和摘要保持不变：

```json
{
  "cmd": "render",
  "mode": "partial",
  "data": {
    "sensor_panel": [
      {"entity_id": "sensor.shi_wai_wendu", "label": "室外温度", "value": "29°C", "trend": "↑", "remark": ""}
    ],
    "events_panel": [
      {"time": "15:02", "text": "客厅有人移动", "level": "info"}
    ]
  }
}
```

此请求只重绘 `sensor_panel` 和 `events_panel` 两个 Widget；`network_panel` 和 `summary` 保留上次内容。

响应：
```json
{"ok": true}
{"ok": false, "error": "display busy"}
```

Daemon 内部串行处理：收到 `render` 后标记为 busy，完成后恢复 idle。重叠请求直接返回 `display busy`。

#### `clear` — 清屏

请求：`{"cmd": "clear"}`
响应：`{"ok": true}`
流程：`epd.init()` → `epd.Clear()` → `epd.sleep()`

#### `sleep` — 深度休眠

请求：`{"cmd": "sleep"}`
响应：`{"ok": true}`
流程：`epd.sleep()`

#### `status` — 查询状态

请求：`{"cmd": "status"}`
响应：`{"ok": true, "status": "idle", "last_render": "2026-05-30T15:30:00", "mode": "partial"}`

#### `shutdown` — 关闭 Daemon

请求：`{"cmd": "shutdown"}`
响应：`{"ok": true}` (Daemon 退出)

---

## 渲染器 (Renderer) 架构

### 整体流程

```
final_output JSON
    │
    ▼
Layout.render_full(data) 或 Layout.render_partial(changed_widgets)
    │
    ├─ 创建/复用 800×480 PIL Image (mode='1')
    ├─ _draw_chrome(draw)          ← 列标题 + 分隔线（仅全刷）
    ├─ 遍历 widgets:
    │   ├─ widget.clear(draw)      ← 仅局部刷时擦除变化区域
    │   └─ widget.render(draw, data[widget_id])
    ▼
PIL Image → epd.getbuffer() → 48000 字节 → e-Paper
```

### 核心类

```python
class Widget(ABC):
    """所有 Widget 的抽象基类。"""
    widget_id: str          # 唯一标识，对应 final_output 的 key
    bounds: tuple[int,int,int,int]  # (x, y, w, h)

    @abstractmethod
    def render(self, draw: ImageDraw, data) -> None: ...
    def clear(self, draw: ImageDraw) -> None: ...  # 用白色矩形擦除 bounds 区域

class TableWidget(Widget):
    """两列表格 (名称 | 数值)。用于 sensor_panel / network_panel。"""
    col_ratios: tuple[float,float]  # 名称列:数值列 宽度比
    row_height: int
    # render(data: list[dict]) → 逐行绘制 label + value + trend

class ListWidget(Widget):
    """逐行列表。用于 events_panel / summary。"""
    row_height: int
    # render(data: list[str|dict]) → 逐行绘制文本

class Layout:
    """屏幕布局管理器。"""
    widgets: dict[str, Widget]  # widget_id → Widget

    def render_full(self, data: dict) -> Image:
        """全刷：创建新画布 → 画 chrome → 渲染所有 widget。"""

    def render_partial(self, data: dict) -> Image:
        """局部刷：复用上次 Image → 只擦除+重绘 data 中存在的 widget。"""
```

### 全刷 vs 局部刷的渲染差异

| | render_full (重量级) | render_partial (轻量级) |
|---|---|---|
| **画布** | 新建白色 Image | 复用 `_last_image` |
| **Chrome** | 绘制列标题 + 所有分隔线 | 不重绘（保留旧 chrome） |
| **Widget** | 渲染 `data` 中全部 widget | 只渲染 `data` 中存在的 widget |
| **未变化 Widget** | 正常渲染 | 保留旧像素不变 |
| **输出** | 完整新位图 | 修改后的位图（未变区域像素相同） |
| **发送** | `epd.display(buf)` 全刷波形 | `epd.display_Partial(buf)` 局部波形 |

### Trend 指示符

| 趋势值 | 显示符号 | 含义 |
|--------|---------|------|
| `↑` | ↑ | 上升 |
| `↓` | ↓ | 下降 |
| `→` | → | 持平 |
| `△` | △ | 新数据（上次没有该传感器） |

### 字体和文本布局

- 标题：16px 粗体（列标题栏）
- 表格内容：14px 常规（TableWidget 默认）
- 列表内容：14px 常规（ListWidget 默认）
- 摘要：16px 常规
- 行高：22px（默认，Widget 可覆盖）
- 边距：10px（Widget 内部 padding）
- 文本截断：超出列宽/Widget 宽自动缩略并加 `…`

---

## Daemon 生命周期

```
启动
  ├─ 加载配置 (lib/config.py)
  ├─ 初始化 epdconfig (GPIO + SPI)
  ├─ socket bind localhost:5150
  ├─ listen
  │
  ├─ 循环:
  │    accept() → 读 JSON → 校验
  │    ├─ cmd=="render"   → renderer.render(data) → epd.display(buf) → 返回 ok
  │    ├─ cmd=="clear"    → epd.init() → epd.Clear() → epd.sleep()
  │    ├─ cmd=="sleep"    → epd.sleep()
  │    ├─ cmd=="status"   → 返回状态 JSON
  │    └─ cmd=="shutdown" → epd.sleep() → 关闭 socket → 退出
  │
  └─ 异常:
       ├─ 校验失败 → 返回 {"ok":false, "error":"..."}
       ├─ GPIO 错误 → log + sleep → 重新初始化
       └─ socket 错误 → log → 继续 accept
```

---

## Systemd 配置

```ini
# /etc/systemd/system/hab-display.service
[Unit]
Description=My Home E-Paper Display Daemon
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/hab
ExecStart=/usr/bin/python3 display_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable hab-display
sudo systemctl start hab-display
sudo systemctl status hab-display
```

---

## 调试

```bash
# 手动启动（前台）
cd /home/pi/hab && python3 display_server.py

# 查看日志
journalctl -u hab-display -f

# 手动发送指令
echo '{"cmd":"status"}' | nc localhost 5150
echo '{"cmd":"clear"}' | nc localhost 5150
echo '{"cmd":"render","mode":"partial","data":{...}}' | nc localhost 5150

# 发送并读取响应
echo '{"cmd":"status"}' | nc -w 2 localhost 5150

# 关闭
echo '{"cmd":"shutdown"}' | nc localhost 5150
```

---

## 实现文件

| 文件 | 角色 | 说明 |
|------|------|------|
| `display_server.py` | 入口 | Socket 监听 + 指令派发 + 流程编排 |
| `lib/display/protocol.py` | 共享 | DisplayCommand/Response dataclass + DisplayClient |
| `lib/display/renderer.py` | 渲染 | Layout + Widget (TableWidget/ListWidget) → PIL 800×480 位图 |
| `lib/display/epaper_driver.py` | 硬件 | 封装 Waveshare epd4in26 EPD 类 |
| `E-Paper_code/.../epd4in26.py` | 官方库 | Waveshare 原始驱动 (不修改) |

## 刷新策略总结

```
每个小时的第5分钟（重量级）：
  refresh_heavyweight.py → LLM 编排 → final_output (全部 widget 数据)
  → DisplayClient.send(render, mode="full", data={sensor_panel, network_panel, events_panel, summary})
  → Daemon: Layout.render_full() → epd.init() → epd.display() → epd.sleep()
     (~4秒全刷，重建所有 Widget + Chrome，清除残影)

每5分钟（轻量级）：
  refresh_lightweight.py → 仅更新数值 + 事件
  → DisplayClient.send(render, mode="partial", data={sensor_panel, events_panel})
  → Daemon: Layout.render_partial() → epd.display_Partial()
     (~0.5秒局部刷，只重绘 sensor_panel 和 events_panel 两个 Widget，无闪烁)
```

**Widget 级别的局部刷新**是轻量级的关键优化：
- 只发送变化的 Widget 数据（减少网络传输）
- 只擦除+重绘变化的 Widget 区域（减少渲染计算）
- 未变化的 Widget 像素不变，配合局部波形实现无闪烁更新
