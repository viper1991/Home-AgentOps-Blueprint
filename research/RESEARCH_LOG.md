# 工具矩阵探索研究日志

从 HA/UniFi API 实际能力出发，通过逐步探索，最终收敛到 6 工具的矩阵设计。

---

## 阶段 1：HA API 能力面探查

### 1.1 入口探测

```
GET /api/         → (无输出, 不暴露目录)
GET /api/config   → HA 2026.5.4, location="我的家", timezone=Asia/Shanghai
GET /api/states   → 500KB JSON, 1090 实体
```

### 1.2 实体全景

1090 实体的 domain 分布：

| domain | 数量 | 对仪表盘有用? |
|--------|------|-------------|
| number | 261 | ❌ 配置参数 |
| sensor | 198 | ✅ 传感器值 |
| event | 150 | ❌ 事件触发 |
| select | 133 | ❌ 选项配置 |
| switch | 128 | ❌ 开关控制 |
| button | 124 | ❌ 触发器 |
| light | 41 | ⚠️ 可显示状态 |
| cover | 13 | ⚠️ 窗帘状态 |
| notify | 13 | ❌ 通知 |
| text | 7 | ❌ |
| binary_sensor | 6 | ✅ 门磁/人体 |
| climate | 6 | ✅ 空调 |
| media_player | 5 | ⚠️ 播放器 |
| conversation | 1 | ❌ |
| zone | 1 | ❌ |
| person | 1 | ⚠️ 人员位置 |
| sun | 1 | ❌ |
| humidifier | 1 | ⚠️ 加湿器 |

**关键发现：198 个 sensor 中，约 111 个有实际值（非 unavailable/unknown）。有用 device_class：temperature(11), humidity(11), battery(10), power(8), atmospheric_pressure(4)。**

### 1.3 实体属性结构

```json
{
  "entity_id": "climate.ke_ting_kong_diao",
  "state": "cool",
  "attributes": {
    "friendly_name": "客厅空调",
    "hvac_modes": ["auto","cool","dry","fan_only","heat","off"],
    "current_temperature": 23,
    "temperature": 22,
    "fan_mode": "medium",
    "preset_mode": "none",
    "swing_modes": ["off","vertical","horizontal","both"]
  }
}
```

**关键发现：climate 实体的 attributes 非常丰富（hvac_modes / current_temp / target_temp / fan / swing / preset），一个实体就能提供仪表盘所需的全部空调信息。Sensor 实体相对简单：device_class + unit + state。**

### 1.4 区域（Area）信息

```
GET /api/areas           → 404 (HA 2026.5.4 不暴露 REST area API)
GET /api/config/area_registry → 404
检查 state.attributes.area_id → 全部为空
```

**关键发现：HA REST API 不暴露区域注册表（仅 WebSocket 有）。但 friendly_name 中隐含房间语义（"客厅空调"、"书房温度计"、"主卧温湿度传感器"等）。 → 决策：实体目录走本地配置文件，手动维护房间分组。**

### 1.5 历史与事件 API

```
GET /api/history/period/{ts}?filter_entity_id=X&end_time=Y
  → 2h 窗口返回 ~9 个数据点
  → 可计算 min/max/avg/trend

GET /api/logbook/{ts}?end_time=Y
  → 2h 返回 122 条
  → 大量噪音: button unavailable, heartbeat, device_tracker 位置更新
  → 有用信号: climate 状态变化, binary_sensor 触发
```

**关键发现：logbook 需要去噪才有用。history 数据稀疏但足以计算趋势。**

---

## 阶段 2：UniFi API 能力面探查

### 2.1 认证机制

```
POST /api/login  {"username","password","remember":true}
  → Set-Cookie: unifises=xxx; csrf_token=yyy
  → 后续请求需同时发送 Cookie + X-Csrf-Token header
```

### 2.2 网络健康 (`/stat/health`)

返回 5 个子系统：wlan, wan, www, lan, vpn

```json
{
  "subsystem": "wan",
  "status": "ok",
  "wan_ip": "<public-wan-ip>",
  "latency": 9,
  "tx_bytes-r": 45191, "rx_bytes-r": 8858,
  "gw_system-stats": {"cpu": "12", "mem": "22", "uptime": "525371"},
  "num_sta": 39
}
```

**关键发现：一个端点覆盖 WAN 全部指标。wlan 子系统还提供 AP 和用户数。**

### 2.3 设备列表 (`/stat/device`)

6 个设备：4 WiFi AP + 1 网关 + 1 交换机

```
客厅AP  U7LT  IP=<ap-ip-3>  ch=6/149   uplink=wire@1000Mbps
主卧AP  U7IW  IP=<ap-ip-4>  ch=11/149  uplink=wire@1000Mbps
书房AP  U7IW  IP=<ap-ip-5>  ch=1/149   uplink=wire@1000Mbps
客卧AP  U7IW  IP=<ap-ip-6>  ch=1/149   uplink=wire@1000Mbps
USG 3P  UGW3                            
POE交换机 US8P60
```

每个 AP 含 `radio_table`（radio/name/channel/num_sta/tx_power/channel_width）。

**关键发现：AP 命名已含房间信息（客厅/主卧/书房/客卧）。4 个 AP 的 2.4G 信道分布在 1/6/11（无同频干扰），5G 全在 149。**

### 2.4 客户端列表 (`/stat/sta`)

39 在线客户端。每个含：

```
hostname, IP, signal(dBm), rssi, channel, radio(ng/na),
ap_mac, uptime, tx_rate, rx_rate
```

信号分析：范围 -71~-24dBm，平均 -53dBm，无弱信号客户端（全部 >-75dBm）。

**关键发现：客户端信号普遍健康。`ap_mac` 需配合 device 表做 AP 名称映射。**

### 2.5 周边 AP 干扰 (`/stat/rogueap`)

**441 个周围 AP！** 深度分析：

| 频段 | AP 数量 | 评估 |
|------|---------|------|
| 2.4GHz (ng) | 432 | 极度拥塞 |
| 5GHz (na) | 9 | 洁净 |

2.4GHz 信道分布：ch1=168, ch6=104, ch11=117 — 三个主信道均严重拥塞。

13 个强干扰源 (>-80dBm)，最近的可识别邻居包括某华为路由(-63dBm)、某小米设备(-73dBm)、某 TP-LINK 路由(-79dBm)。

**关键发现：这是最有价值的 UniFi 深度数据。2.4G 拥塞信息可作为摘要建议（"建议使用5G WiFi"）。**

### 2.6 网络事件 (`/stat/event`)

返回 EVT_WU_Connected / EVT_WU_Disconnected / EVT_WU_Roam 事件。

**关键发现：客户端频繁上下线和漫游是正常行为，不需要全部展示。应与 HA 事件合并去噪后精选。**

### 2.7 频谱扫描 (`/stat/spectrum-scan`)

端点存在但 `spectrum_table` 为空 — AP 未启用频谱扫描功能。

**关键发现：此端点不可用于实时分析。**

---

## 阶段 3：工具矩阵推导

### 推导原则

1. **工具不重复快照已有信息** — 首轮快照已包含实体目录+状态+网络+事件摘要，工具用于"深挖"
2. **一个工具对应一组 API 端点** — 避免 LLM 需要理解原始 API 语义
3. **粒度适中** — 太细碎会增加交互轮数，太粗则失去灵活性

### HA 端推导

| API 能力 | 直接暴露? | 决策 |
|----------|----------|------|
| /api/states (全量) | 1090 实体, 500KB | ❌ 不让 LLM 直接面对 — 实体目录走本地配置 |
| /api/states/{id} (单实体) | 精确查询 | ✅ → `get_sensor_details` |
| /api/history/period (历史) | 时序数据 | ✅ → `get_trend` (带计算) |
| /api/logbook (事件) | 噪音多 | ✅ → `get_events` (带去噪) |
| /api/areas | 404 | ❌ → 本地配置补偿 |

### UniFi 端推导

| API 能力 | 深度分析价值 | 决策 |
|----------|------------|------|
| /stat/health | WAN 基本状态 | ✅ → `get_network_health` |
| /stat/device + /stat/rogueap | 信道拥塞 + 干扰 | ✅ → `get_wifi_environment` (合并分析) |
| /stat/sta | 客户端信号 | ✅ → `get_client_status` |
| /stat/event | 网络事件 | ⚠️ 合并到 `get_events` |

**拆分理由：3 个独立工具而非 1 个单体，因为 (a) rogueap 返回 441 条数据很重，不应每次都拉；(b) LLM 在关注 Wi-Fi 干扰时才需 `get_wifi_environment`；(c) 关注特定设备连接时才需 `get_client_status`。**

### 为什么移除 `discover_entities`

初版设计包含运行时实体发现工具，但实际探查发现：
- HA REST API **不暴露区域注册表**（仅 WebSocket 有）
- 1090 实体中大部分是噪音，运行时过滤逻辑复杂且不可靠
- 实体 ID 和房间的映射关系本质上是**人工知识**（"这个 sensor 在书房"）

→ 决策：实体目录走 `config/entity_catalog.yaml` 本地配置文件，手动维护。首轮快照直接发送。

### 为什么没有功耗工具

探查确认：HA 中有 8 个 `device_class=power` 的 sensor，但用户反馈无实际功耗传感器。→ 不设独立工具。如果未来需要，LLM 可通过 `get_sensor_details` 查询。

---

## 阶段 4：工具设计定型

### 最终矩阵（6 + 1）

| # | 工具 | API 映射 | 设计要点 |
|---|------|---------|---------|
| 1 | `get_sensor_details` | HA states/{id} | 限 8 个/次，返回完整 attributes |
| 2 | `get_trend` | HA history/period | 限 3 次，自动计算 min/max/avg/trend/delta |
| 3 | `get_events` | HA logbook + UniFi event | 合并去噪，按 category 过滤 |
| 4 | `get_network_health` | UniFi health | WAN+WLAN 摘要 |
| 5 | `get_wifi_environment` | UniFi device + rogueap | 信道分析 + 干扰评估 |
| 6 | `get_client_status` | UniFi sta + device | 信号质量 + AP 分布 |
| — | `final_output` | — | 结构化仪表盘数据 |

### 工具交互预算

首轮快照自带 ~2500 tokens 上下文。6 个工具按场景按需调用：

- **快速路径**（快照足够）：0 工具调用 → 1 轮完成
- **典型路径**（确认趋势+事件）：2-3 工具调用 → 2 轮完成
- **深度路径**（检查网络环境）：4-5 工具调用 → 3 轮完成

---

## 附录：示例 API 响应

### HA /api/states 单实体示例

```json
{
  "entity_id": "climate.ke_ting_kong_diao",
  "state": "cool",
  "attributes": {
    "hvac_modes": ["auto","cool","dry","fan_only","heat","off"],
    "current_temperature": 23,
    "temperature": 22,
    "fan_mode": "medium",
    "preset_mode": "none",
    "swing_modes": ["off","vertical","horizontal","both"],
    "min_temp": 8,
    "max_temp": 30,
    "fan_modes": ["auto","low","medium low","medium","medium high","high"]
  }
}
```

### UniFi /stat/health WAN 子系统

```json
{
  "subsystem": "wan",
  "status": "ok",
  "wan_ip": "<public-wan-ip>",
  "latency": 9,
  "tx_bytes-r": 45191,
  "rx_bytes-r": 8858,
  "num_sta": 39,
  "gw_system-stats": {"cpu": "12", "mem": "22", "uptime": "525371"}
}
```

### UniFi /stat/rogueap (单条)

```json
{
  "radio": "ng",
  "essid": "<neighbor-wifi>",
  "channel": 1,
  "signal": -63,
  "rssi": 33
}
```

---

## 阶段 5：工具矩阵 v2 演进（2026-06-05）

### 5.1 触发：抽象层级审视

回顾阶段 4 定型的矩阵，用户指出一个不对称：

> `get_sensor_details` 看起来像是对 API 的直接封装，是否可以更进一步，比如 `get_room_status` 之类？

重新审视 6 个工具的抽象层级：

```
高层级（语义聚合）
├── get_network_health   ← 聚合多端点为一个语义结果
├── get_wifi_environment ← 聚合 + 主动生成 assessment
├── get_client_status    ← 聚合 + 分布分析 + 弱信号标记
├── get_events           ← 跨源去噪合并
│
中层级
├── get_trend            ← 单实体 + 历史统计计算
│
低层级（API 裸封装）     ← 问题
└── get_sensor_details   ← GET /api/states/{id} 加批量限制
```

**诊断**：`get_sensor_details` 是唯一要求 LLM 使用 entity_id 的工具。LLM 被迫在快照文本中翻找 `lumi_cn_lumi_xxxxxxxxxxxx_v1_...` 这样的机器 ID，而非用自然语言说"我想了解客厅的情况"。其他 5 个工具均隐藏了端点细节，它却暴露了 API 语义。

### 5.2 根因：快照覆盖不全创造了一个"补洞工具"

为什么 `get_sensor_details` 会存在？因为快照设计存在内在矛盾：

```
entity_catalog.yaml
  ├── rooms: 6 个房间，列出所有实体（含客厅窗帘等）
  └── snapshot_entities: 6 个精选 entity_id（不含窗帘、不含客卧/阳台传感器）
       ↑ 快照只拉取这些的实时值
```

LLM 在首轮看到 catalog 中有「客厅窗帘」，但快照中没有它的实时值 → 需要一个工具来补拉。`get_sensor_details` 本质上是在填补快照覆盖不全的坑。

此外，快照对 climate 实体的展示是简略的（`"cool, 当前23°C→目标22°C, 中等风速"`），如果 LLM 想查看 `hvac_action`（是否真正在制冷？）、`swing_mode`、`preset_mode` 等完整属性，也只能通过 `get_sensor_details`。

→ **与其设计一个低层工具来填坑，不如重新设计工具抽象层级。**

### 5.3 v2 核心决策

**`get_sensor_details` → `get_room_status`**

```
                 v1                              v2
                 ──                              ──
LLM 思考方式:    entity_id 列表                 房间名（自然语言）
LLM 调用示例:    get_sensor_details([            get_room_status("客厅")
                   "climate.ke_ting_kong_diao",
                   "sensor.miaomiaoc_...temp",
                   "sensor.miaomiaoc_...humidity"
                 ])

内部流程:        直接透传 HA API               entity_catalog 查房间 →
                                                 批量 HA API →
                                                 展开 climate 属性

返回语义:        [{entity_id, state,            {room, entities[{...完整属性}]}
                  attributes}]

限制变化:        ≤8 entity_id/次               ≤3 次调用
```

### 5.4 设计原则

1. **按语义域组织，不按 API 端点组织** — LLM 用自然概念思考（房间、设备类型）
2. **entity_catalog 是工具的数据源** — catalog 不再仅是文档；`get_room_status` 通过它查找房间实体，实现「房间名 → entity_id」的映射。这是 entity_catalog 作为**结构化配置**的第一次主动使用
3. **渐进式信息披露** — 快照提供基本状态（免费，~2500 tokens），`get_room_status` 提供完整属性（需工具调用）。LLM 在首轮即可判断整体情况，仅在需要深挖时才调用工具
4. **entity_id 最小化暴露** — `get_trend` 是唯一保留 entity_id 参数的工具，且它从 `get_room_status` 返回值获取，LLM 无需记忆或拼写

### 5.5 渐进式信息披露

| | 快照（首轮，免费） | `get_room_status`（按需，消耗工具调用） |
|---|---|---|
| 传感器数值（温度/湿度） | ✅ | ✅ |
| Climate 基本状态 | ✅ state + 简略描述 | ✅ |
| Climate 完整属性 | ❌ | ✅ hvac_action, current_temp, target_temp, fan_mode 等 |
| 非 snapshot 实体 | ❌ | ✅ 如窗帘、未加入 snapshot 的传感器 |
| Token 成本 | ~2500（固定在首轮） | 每次调用额外消耗 |

设计意图：LLM 在首轮即可判断整体情况（各房间温湿度、空调是否运行）。仅在需要深挖时（如空调状态异常、想查看非 snapshot 设备）才调用 `get_room_status`。

### 5.6 为什么 `get_trend` 仍用 entity_id

趋势查询天然是实体级别的——不想为看客厅温度趋势而拉取整个房间所有实体的历史数据。entity_id 从 `get_room_status` 返回值获取，LLM 无需记忆。

### 5.7 已拒绝的替代方案

| 方案 | 内容 | 拒绝理由 |
|------|------|---------|
| A | 保留但重命名为 `get_entity_attributes` | 换名字，仍是 entity_id 级别 |
| B | 把完整属性塞进快照 | 首轮 token 爆炸（climate 有 20+ 属性字段），且大部分 LLM 不需要 |
| C | 多粒度并行：同时提供 `get_room_status` + `get_climate_detail` + `get_sensor_detail` | 工具过多（9+），增加选择困难，且功能重叠 |

### 5.8 v2 最终矩阵

| # | Tool | 抽象层级 | 数据源 | 限制 |
|---|------|---------|--------|------|
| 1 | `get_room_status` | **房间级** | entity_catalog + HA /api/states | ≤3 次 |
| 2 | `get_trend` | 实体级 | HA /api/history | ≤3 次, ≤4h |
| 3 | `get_events` | 跨域 | HA logbook + UniFi event | — |
| 4 | `get_network_health` | 网络域 | UniFi /stat/health | — |
| 5 | `get_wifi_environment` | 网络域 | UniFi device + rogueap | — |
| 6 | `get_client_status` | 网络域 | UniFi sta + device | — |
| 7 | `final_output` | 输出 | — | panel ≤6 条 |

所有工具现在均为高层语义抽象，无裸 API 封装泄露。

### 5.9 配置变更

```diff
  agent:
    max_rounds: 3
-   max_sensor_details: 8
+   max_room_status_calls: 3
    max_trend_calls: 3
    max_trend_hours: 4
```

### 5.10 回顾：这次演进为什么重要

阶段 1-4 的探索聚焦于「API 能力 → 工具」的**数据驱动推导**——从 HA/UniFi 实际返回中提取可用信息，自然得出了正确的工具数量（6 个）。但数据驱动有其盲区：它倾向于产出与 API 端点一一对应的工具。

阶段 5 的演进是「抽象层级审视」——站在 LLM 的视角问：**这个工具让 LLM 用自然概念思考，还是让它理解 API 语义？** 这是 Agent 工具设计的核心质量指标。

`get_room_status` 还意外强化了 entity_catalog 的价值：它从「给 LLM 看的文档」升级为「工具运行时依赖的结构化配置」——同一份配置，同时服务于快照构建（文档生成）和工具执行（房间→实体映射）。

---

## 阶段 6：工具调用预算收紧 — 1 工具/轮（2026-06-05）

### 6.1 触发

回顾工具调用流程：标准 function calling 模式下，LLM 可以在单次响应中发起多个并行工具调用。这让 LLM 有机会在一个回合内完成多步数据收集。

但用户提出收紧：**每轮 LLM 交互只允许调用 1 个工具。**

### 6.2 决策

```
变更前:                                 变更后:
┌─────────────────────────────┐         ┌─────────────────────────────┐
│  LLM → tool_A + tool_B     │         │  LLM → tool_A              │
│  ↑            ↓             │         │  ↑            ↓            │
│  └── result_A + result_B ──┘         │  └── result_A ───────────┘  │
│  1 轮 = 多工具                       │  LLM → tool_B               │
│                                      │  ↑            ↓             │
│                                      │  └── result_B ────────────┘ │
│                                      │  1 轮 = 1 工具              │
└─────────────────────────────┘         └─────────────────────────────┘
```

### 6.3 变更内容

```diff
  agent:
+   tools_per_round: 1          # 新增：每轮最多调用 1 个工具
-   max_rounds: 3
+   max_rounds: 6               # 增加：总工具预算 ≈ 6（之前隐含多工具/轮）
    max_room_status_calls: 3    # 不变，全局限制
    max_trend_calls: 3          # 不变，全局限制
    max_trend_hours: 4          # 不变
```

### 6.4 理由

**可预测性**：1 工具/轮让 Agent 的行为路径完全可追踪。每步只做一件事，结果直接反馈到下一轮 LLM 上下文。没有"哪个工具结果影响了哪个决策"的歧义。

**上下文更清晰**：多工具并行时，LLM 收到的结果是乱序或批量的，需要自行关联。1 工具/轮则每轮 LLM 看到的是「刚刚调用的工具结果 → 推理 → 下一步决策」，思维链自然对齐。

**预算更精确**：`max_rounds` 现在直接等于"最多可调用的工具总数"。之前多工具/轮时，一个 LLM 响应可能消耗 3 个工具配额，但只算 1 轮。现在一一对应，容量规划直观。

**时序依赖更可靠**：如果工具 B 依赖工具 A 的结果（如 `get_trend` 需要从 `get_room_status` 返回值中获取 entity_id），1 工具/轮天然保证串行顺序，LLM 无需在单次响应中"猜测"工具 B 的参数。

### 6.5 对 Agent Loop 设计的影响

Orchestrator 循环逻辑变为：

```
round = 0
while round <= max_rounds:
    response = llm.chat(messages, tools)
    if response.tool_calls:
        assert len(response.tool_calls) <= 1   # tools_per_round 约束
        result = execute(response.tool_calls[0])
        messages.append(result)
        round += 1
    else:
        break   # 没有工具调用 → LLM 完成，输出 final_output
```

### 6.6 不改变的地方

- 每种工具的全局配额仍独立追踪（`max_room_status_calls: 3`、`max_trend_calls: 3`）
- 首轮快照仍然是"免费"的（不计入工具调用）
- `final_output` 仍然是最后必须调用的结束工具

---

## 阶段 7：UniFi DPI 探索与新工具扩展（2026-06-06）

### 7.1 触发：UniFi API 深度探测

在阶段 2 中，UniFi 探查聚焦于 health/device/sta/rogueap/event 五个端点。本轮对控制器全部 `stat/*` 端点进行系统性探测，发现三个高价值数据源。

### 7.2 DPI 流量分析（`stat/dpi` + `stat/sitedpi` + `stat/stadpi`）

**发现**：控制器 v8.6.9 (USG 3P) 支持完整 DPI 深度包检测，169 个应用、28 个分类、累计 150GB+ 流量数据。

**端点矩阵**：

| 端点 | 方法 | 数据 |
|------|------|------|
| `stat/dpi` | GET | 按分类汇总（28 cat），每类含 app 列表 + rx/tx bytes |
| `stat/sitedpi?type=by_app` | GET | 169 应用流量排行，含 `known_clients`（使用该应用的设备数） |
| `stat/sitedpi?type=by_cat` | GET | 分类流量排行 |
| `stat/stadpi` | **POST** + `macs` | 单客户端 DPI 画像，可查任意设备在干什么 |

**实测亮点**：
- 全站 #1 应用 `未知流量`（142GB，56 台设备）— 大部分为加密流量（TLS/SSL）
- `YouTube` 19.5GB（25 台设备）— 电视/盒子贡献最大
- `抖音` 2.3GB（9 台）— 手机为主
- 单设备画像：`iPhone` → 抖音 1GB + 网页 2GB；`电视盒子` → YouTube 18GB 独占

**ID 编码**：老版控制器 (v8.6.9) 返回纯数字 app_id/cat_id，无 name 字段。新版 UniFi OS 返回字符串 ID（如 `"netflix"`）+ `name`。创建本地映射表 `lib/dpi_apps.py` 解决。

### 7.3 设备花名册（`stat/alluser`）

95 台设备完整记录，含 `hostname`、`mac`、`oui`、`first_seen`、`last_seen`、`last_uplink_name`（最后连接 AP）、`last_radio`（2.4G/5G）、`is_wired`。

**关键能力**：
- **新设备检测**：对比 `first_seen` 与当前时间，24h 内首次出现的设备标记为"新设备"
- **离线追踪**：`last_seen` > 7 天的设备标记为"长期离线"
- **设备分类**：基于 hostname 关键词 + OUI 厂商名推断设备类型（手机/电脑/电视/摄像头/IoT）

### 7.4 网络告警（`stat/alarm`）

338 条历史告警，按 `key` 分类：
- `EVT_GW_WANTransition`：313 次（WAN 线路切换非常频繁！）
- `EVT_AP_Lost_Contact`：15 次
- `EVT_GW_Lost_Contact`：4 次
- `EVT_SW_Lost_Contact`：4 次

**关键能力**：WAN 稳定性评估、AP 掉线频率分析、异常重启检测。备线 313 次切换值得排查物理链路。

### 7.5 工具矩阵 v3

| # | Tool | 数据源 | 设计要点 | 新增/变更 |
|---|------|--------|---------|----------|
| 1 | `get_room_status` | HA | 房间级语义 | — |
| 2 | `get_trend` | HA history | 单实体趋势 | — |
| 3 | `get_events` | HA logbook + UniFi event | 跨域去噪 | — |
| 4 | `get_wifi_environment` | UniFi device + rogueap | WiFi 环境 | — |
| 5 | `get_client_status` | UniFi sta + device | 客户端连接 | — |
| **6** | **`get_traffic_analysis`** | **UniFi DPI** | **全站/单设备流量画像，TOP 应用，异常检测** | **新增** |
| **7** | **`get_device_inventory`** | **UniFi alluser** | **设备盘点，新设备告警，离线设备，类型分布** | **新增** |
| **8** | **`get_network_alarms`** | **UniFi alarm** | **WAN 稳定性评估，AP 掉线，异常重启检测** | **新增** |
| — | `final_output` | — | 仪表盘输出 | — |

### 7.6 工具设计原则（阶段 5 延续）

新工具保持与 v2 一致的抽象层级：

- `get_traffic_analysis`：不暴露 DPI 端点细节，LLM 用 `scope='site'` 或 `scope='device'+mac` 自然调用。内置异常检测逻辑（上传远大于下载等）
- `get_device_inventory`：响应聚合统计 + 可选过滤（`filter='new'/'offline'/'online'`），LLM 无需理解 `first_seen` 时间戳和 OUI 概念
- `get_network_alarms`：`hours_back` 控制时间窗口，自动生成评估文本（"WAN 切换频率异常偏高"），LLM 直接引用

### 7.7 配额建议

| 工具 | max_calls | 理由 |
|------|-----------|------|
| `get_traffic_analysis` | ≤2 | 全站 + 单个可疑设备 |
| `get_device_inventory` | ≤1 | 数据量固定，一次足够 |
| `get_network_alarms` | ≤1 | 告警数据稳定，一次覆盖 |

### 7.8 不采用的端点

| 端点 | 拒绝理由 |
|------|---------|
| `stat/sysinfo` | 控制器 CPU/内存 — 非家庭关注点 |
| `stat/routing` | 双 WAN 路由已在 health 中覆盖 |
| `stat/spectrumscan` | 返回空（AP 不支持） |
| `stat/report` | 数据保留期过短，返回空 |
| `stat/dynamicdns` | 返回空 |
| `rest/*`（网络配置类） | VLAN/DHCP/防火墙 — LLM 不需要，运维面板足够 |
| `self/sites` | 单站点家庭无用 |

### 7.9 快照集成（snapshot.py）

DPI 数据在首轮快照中免费提供给 LLM，无需工具调用：

```
## 流量分析
全站总流量: 390GB
TOP 10 应用:
  未识别流量: ↓112.9GB ↑27.1GB (56台设备)
  HTTP大流量: ↓72.8GB ↑33.6GB (50台设备)
  ...

当前活跃设备 TOP 10（会话流量）:
  iPhone: ↓306MB ↑288MB WiFi 信号=-52dBm 在线45min
  ...
```

LLM 在首轮即可获得全站流量画像，按需调用 `get_traffic_analysis(scope='device', mac='...')` 深挖单设备。

---

## 阶段 8：工具输出精简与纯数据原则（2026-06-06）

### 8.1 触发：工具数据膨胀

首版 8 工具矩阵实测后，发现工具总输出 21,179 chars（~6K tokens），其中 `get_client_status` 独占 10,795 chars（39 设备全量输出）。另有三个工具包含分析结论（assessment/anomalies/device type inference），违反了「工具只提供数据，LLM 做分析」的原则。

### 8.2 纯数据原则

**所有工具移除分析逻辑，只返回原始/聚合数据**：

| 工具 | 移除的分析逻辑 |
|------|-------------|
| `get_wifi_environment` | `assessment` 文本（"2.4GHz 极度拥塞，建议使用5G"） |
| `get_traffic_analysis` | 异常检测（上传远大于下载）、设备类型推断 |
| `get_network_alarms` | WAN 稳定性评估、AP 掉线诊断 |
| `get_device_inventory` | 设备类型分类（手机/电脑/IoT 等推断） |
| `get_client_status` | 弱信号检测（-75dBm 阈值）、平均信号计算 |

保留 `get_network_alarms.note`：一个事实性说明（"WAN 每日定时重拨，6:00/18:00 属正常 ISP PPPoE 刷新"）—— 这不是分析结论，而是背景知识，避免 LLM 误判 313 次切换为故障。

### 8.3 工具输出瘦身

| 优化点 | 工具 | 效果 |
|--------|------|------|
| 默认仅 top5 + 按 MAC 单查 | `get_client_status` | 10,795 → 1,416 / 294 |
| 过滤开关/按钮等无价值实体 | `get_room_status` | 3,364 → 2,801 |
| climate/light/cover/sensor 按类型精简 attrs | `get_room_status` | 2,801 → 1,132 |
| 移除 null 字段、截断 >5 元素列表 | `get_room_status` | — |

type→attrs 白名单：

| type | 保留 key |
|------|---------|
| climate | hvac_action, current_temperature, temperature, fan_mode, swing_mode 等 |
| light | brightness, color_temp_kelvin, effect（非 null 才输出） |
| cover | current_position, is_closed |
| sensor | unit_of_measurement, device_class, state_class |

off 状态的灯 attributes 为空 `{}`，避免传输 14 个效果名 + 8 个 null 字段。

### 8.4 最终指标

```
Tool                            Chars
--------------------------------------
get_room_status                 1,132
get_events                        831
get_wifi_environment              837
get_client_status (top5)        1,416
get_client_status (mac单设备)     294
get_traffic_analysis            2,452
get_device_inventory            1,291
get_network_alarms              1,686
--------------------------------------
TOTAL                           9,939  (-53%)
```

| 指标 | 优化前 | 优化后 | 降幅 |
|------|--------|--------|------|
| 工具总输出 | 21,179 chars | 9,939 chars | **53%** |
| 单工具最大 | 10,795 | 2,452 | **77%** |
| 分析结论 | 4 个工具含 | 0 个工具含 | **100%** |

### 8.5 设计原则固化

1. **工具是数据管道，不是分析师** — 返回结构化数据，不返回诊断文本
2. **渐进式数据获取** — 默认给摘要（top5），LLM 按需深挖（mac 单查）
3. **类型感知的精简** — 不同 entity type 保留不同 attributes，避免无效字段
4. **上下文知识作为 note** — 非分析结论的事实背景可附带（如 WAN 定时重拨说明）
