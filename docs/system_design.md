# HAB — 家庭信息仪表盘（LLM Agent 架构）

三个独立程序 + 共享库。Display Server 常驻后台；轻量/重量刷新由 cron 定时触发，跑完即退。

> **Display Server 架构**: `display_server_architecture.md`
> **Display Server 运维**: `display_server_manual.md`
> **部署运维手册**: `ops.md`
> **研究过程**: `../research/` — 工具矩阵推导与提示词演进

---

## 核心设计理念

### Agent 模式

重量级刷新采用 **LLM Agent 智能体** 模式：HA、UniFi 全部抽象为 **Tool**，LLM 通过 function calling 自主决定调用策略。

### 实体目录 = 本地配置

实体目录不靠运行时 API 发现，而是**手动维护在本地配置文件**。首轮 LLM 交互时，快照构建器读取配置 + 实时拉取值，一并发送。

### 纯实时，仅工作记忆

不缓存任何 API 数据。每次重量级刷新保存输出到 outputs/。最近 5 次 summary 作为工作记忆传给 LLM，用来避免重复话题。轻量刷新不写工作记忆。

---

## 模块总览

```
HAB/
│
├── display_server.py              # 显示守护进程（独占 GPIO，常驻后台）
├── refresh_heavyweight.py         # 重量级刷新：Agent Loop → 全刷
├── refresh_lightweight.py         # 轻量级刷新：数值更新 → 局刷
├── ops_server.py                  # 运维 Web 面板 (端口 8080)
│
├── lib/
│   ├── config.py                  # YAML 配置加载
│   ├── prompts.py                 # 提示词加载器
│   ├── network_panel.py           # 网络面板公共模块（三层共用）
│   ├── interaction_log.py         # LLM 交互日志（JSONL，完整不截断）
│   ├── tool_counter.py            # 工具调用计数器
│   ├── working_memory.py          # 工作记忆: 最近 10 次输出
│   │
│   ├── clients/
│   │   ├── ha_client.py           # HA REST API
│   │   └── unifi_client.py        # UniFi REST API (+ DPI/alluser/alarm)
│   │
│   ├── dpi_apps.py                # DPI 应用/分类 ID 映射表
│   │
│   ├── tools/
│   │   ├── base.py                # Tool ABC + ToolRegistry + 配额追踪
│   │   ├── room_status.py         # get_room_status
│   │   ├── trend.py               # get_trend
│   │   ├── events.py              # get_events
│   │   ├── wifi_env.py            # get_wifi_environment
│   │   ├── client_status.py       # get_client_status
│   │   ├── traffic_analysis.py    # get_traffic_analysis
│   │   ├── device_inventory.py    # get_device_inventory
│   │   ├── network_alarms.py      # get_network_alarms
│   │   └── final_output.py        # final_output
│   │
│   ├── agent/
│   │   ├── snapshot.py            # 首轮快照构建器
│   │   └── orchestrator.py        # Agent Loop 引擎（1-2工具/轮）
│   │
│   ├── llm/
│   │   ├── provider.py            # LLMProvider ABC + LLMResponse
│   │   └── deepseek.py            # DeepSeek (OpenAI SDK)
│   │
│   └── display/
│       ├── protocol.py            # DisplayClient (socket)
│       ├── renderer.py            # Layout + Widget 渲染引擎
│       └── epaper_driver.py       # Waveshare EPD 封装
│
├── config/
│   ├── config.yaml                # 全局配置
│   ├── entity_catalog.yaml        # 实体目录（手动维护）
│   ├── prompts.yaml               # LLM 提示词
│   └── tool_usage.json            # 工具调用计数
├── outputs/                       # 工作记忆（最近 10 次 JSON）
├── logs/interactions/             # LLM 交互日志（JSONL）
└── fonts/
```

---

## 三个程序的关系

```
crontab
  */5 * * * *  refresh_lightweight.py   → DisplayClient(partial) ─┐
  5   * * * *  refresh_heavyweight.py   → DisplayClient(full) ────┤
                                                                   ▼
                                                        display_server.py
                                                        (唯一操作 GPIO)
```

---

## 两级刷新

| | 重量级 | 轻量级 |
|---|---|---|
| **触发** | cron: `5 * * * *` | cron: `*/5 * * * *` |
| **LLM** | ✅ Agent Loop（多轮, 1-2工具/轮） | ❌ |
| **LLM 职责** | sensor_panel 选择 + summary 撰写 | — |
| **sensor_panel** | LLM 选择 ≤6 条传感器 | 按 label 反查 entity_catalog → HA 更新数值 |
| **network_panel** | 公共模块 `lib/network_panel.py` | 同左 |
| **events_panel** | HA logbook + UniFi 聚合 | 同左 |
| **summary** | LLM 生成（3条：概括→深挖→建议） | 保留上次（不刷新） |
| **工作记忆** | 保存到 outputs/ | 不保存 |
| **显示** | 全刷 (~4s) | 局部刷 (~0.5s) |

---

## 工具矩阵（8 + final_output）

LLM 仅控制 sensor_panel + summary。网络面板和事件面板由系统自动生成。

| # | Tool | 功能 | 配额 |
|---|------|------|------|
| 1 | `get_room_status` | 按房间获取实体完整状态 | ≤3 次 |
| 2 | `get_trend` | 单实体历史趋势分析 | ≤3 次, ≤4h |
| 3 | `get_events` | 合并去噪近期事件 | — |
| 4 | `get_wifi_environment` | WiFi 信道拥塞 + 干扰分析 | — |
| 5 | `get_client_status` | 客户端连接质量分析 | — |
| 6 | `get_traffic_analysis` | 全站/单设备 DPI 流量画像 | ≤2 次 |
| 7 | `get_device_inventory` | 设备盘点 + 新设备检测 | ≤1 次 |
| 8 | `get_network_alarms` | WAN/AP 稳定性评估 | ≤1 次 |
| 9 | `final_output` | 提交仪表盘内容（sensor_panel + summary） | — |

快照新增 DPI 流量分析段（全站 TOP 10 应用 + 当前活跃设备 TOP 10）。

---

## 运维 Web 面板

`ops_server.py` 提供局域网运维界面（`http://<Pi-IP>:8080`）：
- 显示服务控制（启动/停止/重启）
- 手动触发轻量/重量刷新
- 日志查看（Display Server / 轻量刷新 / 重量刷新 / LLM 交互）
- 工具调用统计 + Token 消耗预估
- 屏幕预览（读取最新 output 渲染为 PNG）

---

## Agent 配置

```yaml
agent:
  max_rounds: 3               # 首轮后最大交互轮数（第 4 轮仅 final_output）
  tools_per_round: 2          # 每轮最多 2 个工具
  max_room_status_calls: 3
  max_trend_calls: 3
  max_trend_hours: 4
```

---

## LLM 输出规范

- **sensor_panel**: ≤6 条对象，每条只需 `label` + `value`，可选 `trend`/`remark`
  - label 必须与快照「当前状态」中的名称逐字一致
  - 只放传感器实体，不放网络信息
- **summary**: 3 条字符串，每条 ≤50 字，格式：概括 → 深挖 → 建议
- **禁止 emoji**（墨水屏字体不支持）

---

## 网络面板

公共模块 `lib/network_panel.py`，轻量/重量/快照三层共用。

```
WAN   115.204.131.56
备线  100.73.208.224
↑↓    38KB/s 106KB/s
延迟  10ms
客厅AP  ch6 12台  ch149 5台
主卧AP  ch11 7台
书房AP  ch1 3台  ch149 2台
客卧AP  ch1 4台
```

数据来源：UniFi health（WAN/www/wlan/lan）+ devices（port_table/radio_table）+ clients（ap_mac/radio 分组）。

---

## 工作记忆机制

每次重量级刷新：
1. 从 outputs/ 读取最近 5 次 summary
2. 拼接到快照末尾 "## 近期摘要参考"
3. LLM 参考后**避开已讨论的话题**，选新角度

---

## 全局配置 (`config/config.yaml`)

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
  max_tokens_per_turn: 2000
  temperature: 0.3

agent:
  max_rounds: 3
  tools_per_round: 2
  max_room_status_calls: 3
  max_trend_calls: 3
  max_trend_hours: 4

display:
  daemon_host: "127.0.0.1"
  daemon_port: 5150

epaper:
  model: "4in26"
  width: 800
  height: 480

working_memory:
  keep_count: 10
  outputs_dir: "outputs"
  dedup_check_recent: 3
```
