# Display Server 运维手册

## 目录

- [快速入门](#快速入门)
- [Socket 协议](#socket-协议)
- [数据格式](#数据格式)
- [客户端库](#客户端库)
- [运维操作](#运维操作)
- [故障处理](#故障处理)
- [架构概述](#架构概述)

---

## 快速入门

### 安装

```bash
cd /home/pi/hab

# 安装中文字体（如未安装）
sudo apt-get install -y fonts-wqy-microhei

# 创建 systemd 服务
sudo tee /etc/systemd/system/hab-display.service > /dev/null << 'SERVICE'
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
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable hab-display
sudo systemctl start hab-display
```

### 启动 / 停止 / 重启

```bash
sudo systemctl start hab-display      # 启动
sudo systemctl stop hab-display       # 停止
sudo systemctl restart hab-display    # 重启
sudo systemctl status hab-display     # 查看状态
```

### 查看日志

```bash
# 实时日志
sudo journalctl -u hab-display -f

# 最近 50 行
sudo journalctl -u hab-display -n 50 --no-pager

# 查看某时间段的日志
sudo journalctl -u hab-display --since "5 min ago"
```

### 前台调试模式

```bash
cd /home/pi/hab

# 前台启动（按 Ctrl+C 停止）
python3 display_server.py

# 使用 Mock 驱动（在非树莓派环境测试）
python3 display_server.py --mock
```

---

## Socket 协议

### 通信格式

```
TCP 127.0.0.1:5150
JSON 消息
长度前缀（4 字节大端 uint32）+ JSON 负载（UTF-8）  
单次请求-响应，无长连接
```

也兼容 `JSON + \n` 格式，可用 `nc` 手动调试。

### 指令列表

| 指令 | 功能 | 耗时 |
|------|------|------|
| `render` | 渲染并显示 | 全刷 ~4s / 局部刷 ~0.5s |
| `clear` | 清屏（全刷全白） | ~5s |
| `sleep` | 深度休眠 | 立即 |
| `status` | 查询状态 | 立即 |
| `shutdown` | 关闭守护进程 | ~2s |

---

### render — 渲染并显示

#### 全刷（重量级刷新）

写入两片 RAM → 全刷波形（约 4 秒，屏幕闪烁一次）。

```json
{
  "cmd": "render",
  "mode": "full",
  "data": {
    "sensor_panel": [
      {"label": "室外温度", "value": "28°C", "trend": "↑"},
      {"label": "室外湿度", "value": "65%", "trend": "→"}
    ],
    "network_panel": [
      {"label": "WAN", "value": "在线 12ms", "detail": "↓3.2M ↑1.1M"},
      {"label": "AP", "value": "3/3 在线"}
    ],
    "events_panel": [
      {"time": "14:52", "text": "大门门锁开→关"}
    ],
    "summary": [
      "室外28°C室内均温25.8°C，全屋正常。",
      "3台AP在线23设备，功耗1.2kW。"
    ]
  }
}
```

#### 局部刷（轻量级值更新）

仅更新指定 Widget，其他区域保留上次内容。无闪烁（约 0.5 秒）。

```json
{
  "cmd": "render",
  "mode": "partial",
  "data": {
    "sensor_panel": [
      {"label": "室外温度", "value": "29°C", "trend": "↑"}
    ],
    "events_panel": [
      {"time": "15:02", "text": "客厅有人移动"}
    ]
  }
}
```

**局部刷的原理**：Layout 复制上次渲染的 PIL Image → 只擦除 + 重绘 `data` 中存在的 Widget → 未变化的 Widget 像素保留 → 发送完整 48000 字节帧缓冲到 EPD，但局部波形只翻转变化的像素。

#### data 字段映射

| data key | Widget 类型 | 位置 | 说明 |
|----------|------------|------|------|
| `sensor_panel` | TableWidget | 左上列 | 名称 + 值 + 趋势，支持 detail |
| `network_panel` | TableWidget | 中上列 | 同左，+ 带宽等 detail |
| `events_panel` | ListWidget | 右上列 | 时间 + 事件文本 |
| `summary` | ListWidget | 底部全宽 | 纯文本行 |

#### 请求示例

**只更新网络面板**：
```json
{"cmd":"render","mode":"partial","data":{"network_panel":[{"label":"WAN","value":"在线 15ms","detail":"↓4.1M ↑0.8M"}]}}
```

**只更新事件**：
```json
{"cmd":"render","mode":"partial","data":{"events_panel":[{"time":"18:00","text":"客厅有人移动"}]}}
```

#### 自适应字号

Widget 根据传入数据的行数和最长文本自动计算字号和行高，填满 Widget 区域，不截断不换行。

| 数据行数 | 传感器面板字号 | 事件面板字号 | 摘要字号 |
|---------|-------------|------------|---------|
| 1 条 | 80px | 80px | 80px |
| 3 条 | 48px | 38px | — |
| 5 条 | 30px | 24px | — |
| 7 条 | 27px | 18px | — |
| 2 行摘要 | — | — | 40px |

---

### clear — 清屏

清为全白，全刷波形。

**请求：** `{"cmd": "clear"}`
**响应：** `{"ok": true}`
**耗时：** ~5 秒

---

### sleep — 深度休眠

关闭 SPI/GPIO，EPD 进入微功耗模式（低至 0.0005mA）。再次 render 时会自动 re-init。

**请求：** `{"cmd": "sleep"}`
**响应：** `{"ok": true}`

---

### status — 查询状态

**请求：** `{"cmd": "status"}`

**响应：**
```json
{
  "ok": true,
  "status": "idle",
  "last_render": "2026-06-04T18:30:00",
  "mode": "partial"
}
```

- `status`: `"idle"` 或 `"busy"`（正在渲染）
- `last_render`: 上次 render 完成时间（ISO 8601）
- `mode`: 上次刷新模式 `"full"` / `"partial"` / `"idle"`

---

### shutdown — 关闭守护进程

**请求：** `{"cmd": "shutdown"}`
**响应：** `{"ok": true}`（守护进程退出）

服务退出前自动清屏 + 深度休眠。

---

## 客户端库

Python 脚本通过 `lib/display/protocol.py` 的 `DisplayClient` 发送指令：

```python
from lib.display.protocol import DisplayClient

client = DisplayClient()                # 127.0.0.1:5150
client = DisplayClient("192.168.1.100") # 远程地址

# 渲染
client.render(data, mode="full")       # 全刷
client.render(data, mode="partial")    # 局部刷

# 其他
client.clear()
client.sleep()
client.status()  # 返回 dict
client.shutdown()
```

`render()` 返回 `True/False`，`status()` 返回状态 dict。

### 手动调试（无需客户端库）

通过 `nc` 直接发 JSON（行协议兼容）：

```bash
# 查状态
echo '{"cmd":"status"}' | nc -w 2 localhost 5150

# 清屏
echo '{"cmd":"clear"}' | nc -w 5 localhost 5150

# 局部刷新
echo '{"cmd":"render","mode":"partial","data":{"events_panel":[{"time":"18:00","text":"test"}]}}' | nc -w 3 localhost 5150

# 关闭
echo '{"cmd":"shutdown"}' | nc -w 2 localhost 5150
```

> `nc` 测试使用换行符终止 JSON，无需长度前缀。Display Server 自动兼容两种格式。

---

## 运维操作

### 开机自启

```bash
sudo systemctl enable hab-display
```

### 手动发送 render 进行测试

```bash
# 从本地向远程 Pi 发送
echo '{"cmd":"render","mode":"full","data":{"sensor_panel":[{"label":"Test","value":"OK"}],"network_panel":[],"events_panel":[],"summary":["Display Server Test","running since $(date +%H:%M)"]}}' | nc -w 10 <pi-ip> 5150
```

### 更新代码后重启

```bash
# 在开发机上编辑完成后拷贝到 Pi
scp display_server.py pi@<pi-ip>:~/hab/
scp lib/display/renderer.py pi@<pi-ip>:~/hab/lib/display/

# 重启服务
ssh pi@<pi-ip> "sudo systemctl restart hab-display"
```

### 检查服务是否正常运行

```bash
sudo systemctl status hab-display
sudo journalctl -u hab-display -n 10 --no-pager
```

正常启动日志：
```
=== HAB Display Server ===
EPD: 4in26 (800x480)
Layout: 4 widgets registered
Listening on 127.0.0.1:5150
Loaded font: /usr/share/fonts/truetype/wqy/wqy-microhei.ttc (title=22)
Idle screen displayed
```

### 夜间降频

Display Server 本身无调度逻辑，由外部 cron 控制刷新频率：

```cron
*/5 * * * *  cd /home/pi/hab && python3 refresh_lightweight.py
5 * * * * *  cd /home/pi/hab && python3 refresh_heavyweight.py
```

脚本内部自检是否该跑（夜间跳过/降频）。Display Server 只响应收到的指令。

---

## 故障处理

### 连接被拒绝

```bash
echo '{"cmd":"status"}' | nc -w 2 localhost 5150
# 无响应 → 服务未运行

sudo systemctl start hab-display
sudo journalctl -u hab-display -n 20 --no-pager  # 查看原因
```

常见原因：
- GPIO busy（上次进程未完全退出）：`sudo pkill -9 -f display_server` 后重启
- 端口冲突：检查 `netstat -tlnp | grep 5150`
- 无硬件权限：确认以 `pi` 用户运行，属于 `gpio` / `spi` 组

### 局部刷新出现残留/叠加

全刷必须使用 `display_Base()`（写入两片 RAM），否则局部刷的基准画面不正确。

确认服务器日志中的命令调用：
```
18:27:58 [INFO] display_server: Full render: sensor_panel:7, ...
```
如果硬件调用是 `display_Base`，则双 RAM 写入正常。

手动触发一次全刷可修复：
```bash
echo '{"cmd":"render","mode":"full","data":{"sensor_panel":[{"label":"修复","value":"OK"}],"network_panel":[],"events_panel":[],"summary":["全刷修复"]}}' | nc -w 10 localhost 5150
```

### 显示方框/乱码

安装了中文字体后仍需重启服务才能生效：
```bash
sudo apt-get install -y fonts-wqy-microhei
sudo systemctl restart hab-display
```

确认日志使用了正确字体：
```
Loaded font: .../wqy/wqy-microhei.ttc (title=22)
```

### render 超时

全刷需要 ~4 秒，局部刷需要 ~0.5 秒。客户端 socket timeout 应设为至少 10 秒（全刷）或 3 秒（局部刷）。

`DisplayClient` 默认读写超时 30 秒，无需调整。

### 日志级别

```bash
# 临时提高日志级别观察问题
export LOG_LEVEL=DEBUG
python3 display_server.py

# 或修改 display_server.py 中的 logging.basicConfig:
# level=logging.DEBUG
```

---

## 架构概述

### 进程关系

```
┌──────────────────────┐      TCP 127.0.0.1:5150      ┌──────────────────────┐
│ refresh_heavyweight  │ ────── render (full) ──────▶ │                      │
│ (cron 每小时)        │                              │   display_server.py  │
├──────────────────────┤                              │   常驻后台           │
│ refresh_lightweight  │ ────── render (partial) ───▶ │   Layout + Widget    │
│ (cron 每5分钟)       │                              │   → PIL → EPD        │
└──────────────────────┘                              └──────────────────────┘
```

- `display_server.py` — 唯一操作 GPIO/SPI 的进程，常驻后台
- `refresh_heavyweight.py` — cron 触发，LLM 编排内容，全刷
- `refresh_lightweight.py` — cron 触发，更新数值，局部刷

### 文件结构

```
display_server.py              # 入口: socket 监听 + 指令派发
lib/
  display/
    protocol.py                # DisplayClient (socket 封装)
    renderer.py                # Layout + Widget 渲染引擎
    epaper_driver.py           # Waveshare EPD 硬件封装
  config.py                    # YAML 配置加载
E-Paper_code/.../epd4in26.py   # 官方 Waveshare 驱动 (不修改)
config/config.yaml              # 所有配置
```

### 刷新流程

```
全刷 (mode=full):
  Layout.render_full(data) → new PIL Image + Chrome + 所有 Widget
  → epd.init() → epd.display_base(img) → 双 RAM 全刷 ~4s

局部刷 (mode=partial):
  Layout.render_partial(data) → 复用上次 PIL Image → 只擦除+重绘指定 Widget
  → epd.display_partial(img) → 单 RAM 局部波形 ~0.5s
```

### Widget 自适应

| Widget | 数据类型 | 自适应维度 | 显示特性 |
|--------|---------|-----------|---------|
| TableWidget | sensor_panel / network_panel | 行高 + 字号 | label/value 两列，支持 detail 副行 |
| ListWidget | events_panel / summary | 行高 + 字号 | 纯文本行，不换行不截断 |

字号由数据行数和最长文本共同决定（二分查找 [10, 80]px 范围），确保内容完整填满 Widget 区域。
