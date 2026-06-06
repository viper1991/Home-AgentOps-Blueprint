# HAB 运维手册

家庭信息仪表盘系统。墨水屏显示 HA 传感器数据 + UniFi 网络状态，LLM Agent 自动编排内容。

---

## 目录

- [系统架构](#系统架构)
- [文件结构](#文件结构)
- [快速部署](#快速部署)
- [启动与停止](#启动与停止)
- [配置](#配置)
- [双级刷新机制](#双级刷新机制)
- [LLM Agent](#llm-agent)
- [日志与监控](#日志与监控)
- [常见故障处理](#常见故障处理)
- [开发指南](#开发指南)

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                        Raspberry Pi                          │
│                                                              │
│  crontab                                                     │
│   */5 * * * *  refresh_lightweight.py  ───┐                  │
│   5 * * * *    refresh_heavyweight.py  ───┤                  │
│                                           ▼                  │
│                              DisplayClient(127.0.0.1:5150)   │
│                                      │                       │
│                                      ▼                       │
│                           display_server.py                  │
│                           (常驻后台, systemd)                 │
│                                │                             │
│                                ▼                             │
│                    Waveshare 4.26" e-Paper                   │
│                    (SPI/GPIO, 800×480)                       │
│                                                              │
│  对外连接:                                                    │
│    HA REST API  ← <your-ha-ip>:8123                          │
│    UniFi Controller ← <your-unifi-ip>:8443                   │
│    DeepSeek API ← api.deepseek.com                          │
└──────────────────────────────────────────────────────────────┘
```

### 进程模型

| 进程 | 类型 | 说明 |
|------|------|------|
| `display_server.py` | systemd 常驻 | 唯一操作 GPIO/SPI，TCP 5150 接收指令 |
| `ops_server.py` | systemd 常驻 | Web 运维面板，端口 8080 |
| `refresh_heavyweight.py` | cron 触发 | LLM Agent 全量刷新，跑完即退 |
| `refresh_lightweight.py` | cron 触发 | 数值更新局部刷新，跑完即退 |

---

## 文件结构

```
HAB/
├── display_server.py           # 墨水屏显示守护进程
├── refresh_heavyweight.py      # 重量级刷新（LLM Agent）
├── refresh_lightweight.py      # 轻量级刷新（数值更新）
│
├── lib/
│   ├── config.py               # YAML 配置加载
│   ├── prompts.py              # LLM 提示词加载器
│   ├── network_panel.py        # 网络面板公共模块
│   ├── interaction_log.py      # LLM 交互日志（JSONL，完整不截断）
│   ├── tool_counter.py         # 工具调用计数器
│   ├── working_memory.py       # 工作记忆（最近 10 次输出）
│   │
│   ├── clients/
│   │   ├── ha_client.py        # HA REST API
│   │   └── unifi_client.py     # UniFi REST API
│   │
│   ├── tools/
│   │   ├── base.py             # Tool ABC + ToolRegistry + 配额追踪
│   │   ├── room_status.py      # get_room_status
│   │   ├── trend.py            # get_trend
│   │   ├── events.py           # get_events
│   │   ├── wifi_env.py         # get_wifi_environment
│   │   ├── client_status.py    # get_client_status
│   │   └── final_output.py     # final_output
│   │
│   ├── agent/
│   │   ├── snapshot.py         # 首轮快照构建器
│   │   └── orchestrator.py     # Agent Loop 引擎（1-2工具/轮）
│   │
│   ├── llm/
│   │   ├── provider.py         # LLMProvider ABC
│   │   └── deepseek.py         # DeepSeek (OpenAI SDK)
│   │
│   └── display/
│       ├── protocol.py         # DisplayClient (socket)
│       ├── renderer.py         # Layout + Widget 渲染引擎
│       └── epaper_driver.py    # Waveshare EPD 封装
│
├── config/
│   ├── config.yaml             # 全局配置
│   ├── entity_catalog.yaml     # 实体目录（手动维护）
│   └── prompts.yaml            # LLM 提示词
│
├── outputs/                    # 工作记忆（最近 10 次 JSON）
├── logs/
│   ├── refresh_heavyweight.log  # 重量刷新日志
│   ├── refresh_lightweight.log  # 轻量刷新日志
│   └── interactions/            # LLM 交互日志（JSONL）
├── fonts/                      # 中文字体
│
├── OPS.md                      # 本文件
├── DISPLAY_SERVER_MANUAL.md    # 显示服务器详细手册
├── RESEARCH_LOG.md             # 设计探索日志
└── prompt_log.md               # 提示词演进日志
```

---

## 快速部署

### 1. 初始设置

```bash
# 装依赖
pip3 install requests PyYAML Pillow openai --break-system-packages

# 配置 API Key（三处）
echo 'export DEEPSEEK_API_KEY=sk-xxxxx' >> ~/.bashrc
echo 'DEEPSEEK_API_KEY=sk-xxxxx' | sudo tee -a /etc/environment
(crontab -l 2>/dev/null; echo 'DEEPSEEK_API_KEY=sk-xxxxx') | crontab -

# 创建目录
mkdir -p outputs logs/interactions config
```

### 2. 配置文件

`config/config.yaml` — 修改 HA/UniFi 地址和凭证：

```yaml
ha:
  url: "http://<your-ha-ip>:8123"
  token: "<ha-long-lived-access-token>"

unifi:
  url: "https://<your-unifi-ip>:8443"
  username: "<read-only-username>"
  password: "<password>"
  site: "default"

llm:
  provider: "deepseek"
  model: "deepseek-v4-flash"
  base_url: "https://api.deepseek.com"
  api_key_env: "DEEPSEEK_API_KEY"
```

### 3. 实体目录

`config/entity_catalog.yaml` — 手动维护家庭设备清单：

```yaml
rooms:
  - name: 客厅
    entities:
      - { id: sensor.xxx_temperature, label: 客厅温湿度, type: temperature }
      - { id: sensor.xxx_humidity, label: 客厅温湿度, type: humidity }
      - { id: climate.ke_ting_kong_diao, label: 客厅空调, type: climate }

snapshot_entities:
  - sensor.xxx_temperature
  - sensor.xxx_humidity
```

**温湿度同 label**：温度传感器和湿度传感器如果属于同一设备，给相同的 label，显示时会自动合并为一行（如 `客厅温湿度 26°C / 60%`）。

### 4. 同步代码到树莓派

```bash
# 从开发机
tar cz --exclude='__pycache__' \
  --exclude='logs/interactions' --exclude='outputs/*.json' \
  -C /path/to/hab . | ssh pi@<pi-ip> \
  "cd ~/hab && tar xz --overwrite"
```

---

## 夜间休眠

22:00-08:00 墨水屏关闭以延长硬件寿命：

| 时间 | 操作 |
|------|------|
| 22:00 | cron 关闭 Display Server |
| 07:30 | cron 启动 Display Server |
| 22:00-08:00 | 刷新脚本自检跳过，不执行任何刷新 |

刷新脚本中的休眠逻辑：
```python
hour = datetime.now().hour
if hour >= 22 or hour < 8:
    return  # 夜间休眠，跳过
```

---

## 启动与停止

### 显示服务

```bash
# 首次部署时启用开机自启
sudo systemctl enable hab-display

# 日常操作
sudo systemctl start hab-display      # 启动
sudo systemctl stop hab-display       # 停止
sudo systemctl restart hab-display    # 重启
sudo systemctl status hab-display     # 查看状态
sudo journalctl -u hab-display -f     # 实时日志
```

### OPS Web 面板

```bash
# 首次部署时启用开机自启
sudo systemctl enable hab-ops

# 日常操作
sudo systemctl start hab-ops          # 启动
sudo systemctl stop hab-ops           # 停止
sudo systemctl restart hab-ops        # 重启
sudo systemctl status hab-ops         # 查看状态
```

访问 `http://<Pi-IP>:8080` 打开运维面板：
- 显示服务控制（启动/停止/重启）
- 手动触发轻量/重量刷新
- 日志查看（5 个 tab：Display Server / 轻量 / 重量 / LLM 交互 / 工具统计）
- 屏幕预览（读取最新 output 渲染为 PNG）
- DEEPSEEK_API_KEY 通过 systemd drop-in 注入（`/etc/systemd/system/hab-ops.service.d/env.conf`）

### 手动触发刷新

```bash
# 首次初始化（从 snapshot_entities 构建初始显示）
python3 refresh_lightweight.py

# 增量更新（保留 summary，刷新传感器/网络/事件）
python3 refresh_lightweight.py

# LLM Agent 全量刷新
python3 refresh_heavyweight.py
```

### crontab 自动调度

```cron
# 重型刷新 — 每小时第 5 分钟（22:00-08:00 休眠跳过）
5 * * * * cd /home/pi/hab && python3 refresh_heavyweight.py >> logs/cron.log 2>&1

# 轻型刷新 — 每 5 分钟，滞后重型 2 分钟（22:00-08:00 休眠跳过）
2,7,12,17,22,27,32,37,42,47,52,57 * * * * cd /home/pi/hab && python3 refresh_lightweight.py >> logs/cron.log 2>&1

# 墨水屏夜间关闭 / 早晨唤醒
0 22 * * * sudo systemctl stop hab-display
30 7 * * * sudo systemctl start hab-display
```

**执行序列**（以 14:00 为例）：
```
14:05  重量级刷新 → 全刷墨水屏
14:07  轻量级刷新 → 数值更新（保留 LLM 摘要）
14:12  轻量级刷新
14:17  轻量级刷新
...
15:05  重量级刷新 → 新一轮 LLM Agent 分析
```

**设置 crontab**：
```bash
crontab -e
# 粘贴上述两行，保存退出

# 查看当前定时任务
crontab -l

# 查看 cron 执行日志
tail -f ~/hab/logs/cron.log
```

---

## 配置

### config.yaml 关键配置项

| 路径 | 说明 |
|------|------|
| `ha.url` | Home Assistant 地址 |
| `llm.model` | DeepSeek 模型名（当前 `deepseek-v4-flash`） |
| `llm.api_key_env` | API Key 环境变量名 |
| `agent.max_rounds` | LLM 最大交互轮数（默认 3） |
| `agent.tools_per_round` | 每轮最多工具调用数（默认 2） |
| `agent.max_room_status_calls` | get_room_status 全局配额（默认 3） |
| `agent.max_trend_calls` | get_trend 全局配额（默认 3） |
| `display.daemon_port` | Display Server 端口（默认 5150） |

### entity_catalog.yaml 维护指南

**新增设备**：
1. HA 中找到 entity_id
2. 确定归属房间
3. 选择合适的 label（温湿度对用同一 label）
4. 添加到 `rooms[].entities[]`
5. 如需在快照中展示，加入 `snapshot_entities` 列表

**label 命名规范**：

| 实体类型 | label 示例 | 说明 |
|---------|-----------|------|
| 温湿度传感器 | `客厅温湿度` | 同一设备的温湿度用同一 label |
| 空调 | `客厅空调` | 独立 label |
| 灯 | `客厅主灯` | 独立 label |
| 窗帘 | `客厅窗帘` | 独立 label |
| 门磁 | `南阳台门` | 独立 label |

### prompts.yaml 定制

LLM 提示词集中管理在此文件。修改后需运行 `refresh_heavyweight.py` 才会生效。

关键部分：
- `system_prompt` — Agent 角色定义、输出规范
- `messages.*` — 运行时提示词（配额耗尽、JSON 修复等）

---

## 双级刷新机制

### 重量级刷新（`refresh_heavyweight.py`）

```
cron 5 * * * *
↓
SnapshotBuilder.build()
  ├── 读 entity_catalog → 实体目录
  ├── HA 拉 snapshot_entities → 当前状态（温湿度合并）
  ├── UniFi health → 网络状态（主备WAN、速率、客户端）
  └── HA logbook + UniFi events → 近期事件
↓
Orchestrator.run()
  └── Agent Loop（1-2工具/轮，最多 4 轮）
       ├── LLM 调用工具收集信息
       └── LLM → final_output（sensor_panel + summary）
↓
系统自动填充：
  ├── network_panel ← lib/network_panel.py
  └── events_panel ← _update_events()
↓
DisplayClient.render(mode="full") → 墨水屏全刷
WorkingMemory.save()
```

### 轻量级刷新（`refresh_lightweight.py`）

```
cron */5 * * * *
↓
mem.load_last()
├── 无上次输出 → _build_initial_output()
│   └── 从 entity_catalog 读取 → 全刷显示（首次初始化）
│
└── 有上次输出 → 增量更新
    ├── _update_sensor_values()
    │   └── 按 label 查 entity_catalog → HA 批量重拉 → 温湿度合并
    ├── build_network_panel()
    │   └── 公共模块 lib/network_panel.py
    ├── _update_events()
    │   └── HA logbook + UniFi 聚合事件
    └── summary 保留不变
    └── DisplayClient.render(mode="partial") → 局部刷
```

### 职责分工

| | 重量级 | 轻量级 |
|---|---|---|
| 触发 | 每小时 | 每 5 分钟 |
| LLM | ✅ Agent Loop | ❌ |
| sensor_panel | LLM 选择传感器 | 按上轮结构更新数值 |
| network_panel | 系统自动（同轻量） | UniFi 全量刷新 |
| events_panel | 系统自动（同轻量） | HA + UniFi 合并 |
| summary | LLM 生成（3条幽默） | 保留上次 |
| 渲染 | 全刷（~4s） | 局部刷（~0.5s） |
| 工作记忆 | 保存 | 不保存 |

---

## LLM Agent

### 工具列表

| 工具 | 功能 | 配额 |
|------|------|------|
| `get_room_status` | 按房间获取所有实体完整状态 | 3 次 |
| `get_trend` | 单实体历史趋势分析 | 3 次，≤4h |
| `get_events` | 合并去噪近期事件 | 无限制 |
| `get_wifi_environment` | WiFi 信道干扰分析 | 无限制 |
| `get_client_status` | 客户端连接质量分析 | 无限制 |
| `final_output` | 提交仪表盘内容 | 始终可用 |

### 工具调用规则

- 每轮可调 1-2 个工具（`tools_per_round=2`）
- 最后一轮仅 final_output 可用，强制提交
- 每种工具有全局配额，耗尽后移除
- JSON 参数格式错误时自动修复重试（JSON mode）

### LLM 输出限制

LLM 仅控制：
- **sensor_panel** — 从快照选择 ≤6 条传感器（label 必须与快照一致，不要 entity_id）
- **summary** — 3 条字符串（概括→深挖→建议，≤50字/条，禁止 emoji）

自动生成：
- **network_panel** — `lib/network_panel.py` 统一生成
- **events_panel** — HA logbook + UniFi 聚合

### 工作记忆

每次重量级刷新将最近 5 次 summary 传给 LLM（快照末尾「近期摘要参考」），LLM 需避开已讨论话题。

---

## 日志与监控

### LLM 交互日志

每次 LLM 调用的完整输入/输出存储在 `logs/interactions/`：

```bash
# 查看最近一次 Agent 运行的所有轮次
cat logs/interactions/heavyweight_*.jsonl | python -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    print(f\"Round {e['round']} ({e['type']}): {e.get('duration_ms','?')}ms\")
    tc = e.get('response',{}).get('tool_calls',[])
    for t in tc:
        print(f'  -> {t[\"function\"][\"name\"]}')
"
```

### 工作记忆

最近 10 次 `final_output` 存储在 `outputs/` 目录：

```bash
ls -lt outputs/
python3 -c "
import json
with open('outputs/最新文件.json') as f:
    d = json.load(f)
print(json.dumps(d, indent=2, ensure_ascii=False))
"
```

### 显示服务日志

```bash
sudo journalctl -u hab-display -n 50 --no-pager
sudo journalctl -u hab-display --since "5 min ago"
```

---

## 常见故障处理

### 显示服务无法启动

```bash
sudo journalctl -u hab-display -n 20 --no-pager
```

常见原因：
- GPIO busy：`sudo pkill -9 -f display_server` 后重启
- 端口冲突：`netstat -tlnp | grep 5150`

### DeepSeek API 错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `401` | API Key 无效 | 检查 `DEEPSEEK_API_KEY` 环境变量 |
| `400 reasoning_content` | thinking mode 下未回传 reasoning | 已自动处理，如出现检查 `orchestrator.py` 中 `assistant_message` 逻辑 |
| `rate limit` | 请求超限 | 降低 cron 频率或升级 DeepSeek 套餐 |

### UniFi 连接超时

```
UniFi login failed: Read timed out
```

- 增加 `timeout` 参数（当前 30s）
- 检查 UniFi Controller 是否在线
- 网络延迟高时可能首次登录需更长时间

### HA 连接问题

```
HA get_state failed
```

- 检查 `config.yaml` 中 `ha.token` 是否过期
- HA 令牌需在 HA 配置 → 长期访问令牌中重新生成
- 确认 HA 地址和端口可访问

### 墨水屏显示异常

| 现象 | 原因 | 解决 |
|------|------|------|
| 显示方框/乱码 | 缺少中文字体 | `sudo apt install fonts-wqy-microhei` 后重启服务 |
| 局部刷新残留 | 缺少全刷基准 | 手动触发一次全刷 |
| 不显示 | 服务未启动 | `sudo systemctl start hab-display` |

---

## 开发指南

### 添加新工具

1. 在 `lib/tools/` 下创建文件，继承 `Tool` ABC
2. 实现 `name`, `description`, `parameters`, `execute()`
3. 在 `refresh_heavyweight.py` 中注册
4. 同步到 Pi 测试

```python
from lib.tools.base import Tool

class MyNewTool(Tool):
    name = 'my_new_tool'
    description = '工具描述'
    parameters = {
        'type': 'object',
        'properties': {
            'param1': {'type': 'string', 'description': '参数说明'},
        },
        'required': ['param1'],
    }

    def execute(self, param1: str) -> dict:
        # 工具逻辑
        return {'result': 'ok'}
```

### 修改提示词

编辑 `config/prompts.yaml`，无需改代码。修改后运行 `refresh_heavyweight.py` 生效。

### 更新实体目录

编辑 `config/entity_catalog.yaml`，修改后运行 `refresh_lightweight.py`（首次初始化），或等待下次重量级刷新。

### 代码同步

```bash
# 全量同步（首次部署含 E-Paper_code）
tar cz --exclude='__pycache__' --exclude='logs/interactions' --exclude='outputs/*.json' \
  -C /path/to/hab . | ssh pi@<pi-ip> \
  "cd ~/hab && tar xz --overwrite"

# 仅同步代码
tar cz --exclude='__pycache__' \
  --exclude='logs/interactions' --exclude='outputs/*.json' \
  -C /path/to/hab . | ssh pi@<pi-ip> \
  "cd ~/hab && tar xz --overwrite"

# 单文件同步
scp refresh_lightweight.py pi@<pi-ip>:~/hab/
```
