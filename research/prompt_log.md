# 提示词演进日志 — Prompt Log

追踪 LLM 交互提示词、工具定义和数据结构的版本演变。

---

## V1 — 初始设计（2026-06-05）

### 系统提示词

```
你是家庭环境仪表盘的智能体。你的任务是通过可用工具收集信息，最终调用 final_output 提交仪表盘内容。

## 工作流程

1. 首轮快照已包含实体目录、当前状态、网络状态和近期事件。
2. 根据快照判断哪些信息已经足够，哪些需要深挖。
3. 每轮**只能调用 1 个工具**。如果需要多个数据，请在多轮中依次调用。
4. 每轮看到工具结果后，决定下一步：调用另一个工具，或直接提交 final_output。
5. 最终必须调用 final_output 提交仪表盘内容。

## 工具调用约束

- 每轮交互只能调用 1 个工具。如果你生成了多个工具调用，只有第 1 个会执行，其余被丢弃。
- 每种工具的调用次数受全局配额限制。配额耗尽后该工具不可再用。
- 工具调用结果会追加到对话历史中，下一轮你可以看到之前所有结果。

## 输出规范

- summary：1-3 条，每条不超过 20 字
- sensor_panel 不超过 6 条
- network_panel 不超过 6 条
- events_panel 不超过 6 条
- 使用中文
```

### 快照模板（首轮 User Message）

```
## 实体目录

### {房间名}
  {标签} | {类型} | {entity_id}
  ...

## 当前状态

{entity_id}: {值}
{entity_id}: {值}
...

## 网络状态

WAN: {状态}, {延迟}ms, ↓{下行} ↑{上行}, 运行{天数}天
AP: {在线数}/{总数} 在线, {客户端数}用户

## 近期事件

{时间} | {事件描述} | {类别}
{时间} | {事件描述} | {类别}
...
```

### 工具定义（OpenAI Function Calling 格式）

```json
[
  {
    "type": "function",
    "function": {
      "name": "get_room_status",
      "description": "获取指定房间所有实体的完整状态和完整属性（含 climate 的 hvac_action/current_temp/target_temp/fan_mode 等）。房间名从实体目录中获取。",
      "parameters": {
        "type": "object",
        "properties": {
          "room_name": {
            "type": "string",
            "description": "房间名",
            "enum": ["室外", "客厅", "主卧", "书房", "客卧", "阳台"]
          }
        },
        "required": ["room_name"],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_trend",
      "description": "获取单个实体的历史趋势分析，返回当前值、最小值、最大值、平均值、趋势方向(↑↓→)和变化量。entity_id 从 get_room_status 返回值中获取。",
      "parameters": {
        "type": "object",
        "properties": {
          "entity_id": {
            "type": "string",
            "description": "实体 ID，如 climate.ke_ting_kong_diao"
          },
          "hours_back": {
            "type": "number",
            "description": "回溯小时数，范围 0.5-4.0",
            "minimum": 0.5,
            "maximum": 4.0
          }
        },
        "required": ["entity_id", "hours_back"],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_events",
      "description": "获取近期事件，自动合并 HA logbook 和 UniFi 事件并去噪（过滤 heartbeat/button_unavailable/device_tracker 等噪音）。",
      "parameters": {
        "type": "object",
        "properties": {
          "hours_back": {
            "type": "number",
            "description": "回溯小时数，默认 2",
            "minimum": 0.5,
            "maximum": 24
          },
          "categories": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": ["climate", "security", "network", "door"]
            },
            "description": "事件类别过滤。不传则返回全部类别。"
          }
        },
        "required": [],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_network_health",
      "description": "获取网络健康状态概览，包括 WAN 连接状态、公网 IP、延迟、上下行速率、运行时间、设备 CPU/内存使用率，以及 WLAN 客户端数和 AP 在线状态。",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_wifi_environment",
      "description": "获取 WiFi 环境分析，包括自家 AP 列表及信道配置、周围干扰 AP 列表及信号强度、信道拥塞评估和建议。",
      "parameters": {
        "type": "object",
        "properties": {
          "band": {
            "type": "string",
            "enum": ["2g", "5g", "all"],
            "description": "频段过滤。2g=2.4GHz, 5g=5GHz, all=全部。默认 all。"
          }
        },
        "required": [],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_client_status",
      "description": "获取 WiFi 客户端连接状态和质量分析，包括客户端总数、平均信号强度、弱信号客户端列表、按 AP 的分布统计。",
      "parameters": {
        "type": "object",
        "properties": {
          "filter": {
            "type": "string",
            "enum": ["weak", "all"],
            "description": "过滤条件。weak=只返回弱信号客户端(-75dBm以下)，all=返回全部客户端。默认 all。"
          }
        },
        "required": [],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "final_output",
      "description": "提交最终的仪表盘内容。调用此工具后本轮交互结束，不可再调用其他工具。",
      "parameters": {
        "type": "object",
        "properties": {
          "sensor_panel": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "entity_id": {
                  "type": "string",
                  "description": "实体的 entity_id"
                },
                "label": {
                  "type": "string",
                  "description": "显示标签，如"客厅温度""
                },
                "value": {
                  "type": "string",
                  "description": "显示值，如"26.5°C"、"47%""
                },
                "trend": {
                  "type": "string",
                  "enum": ["↑", "↓", "→"],
                  "description": "趋势方向"
                },
                "remark": {
                  "type": "string",
                  "description": "备注，如"较舒适"、"较 2h 前 +2°C""
                }
              },
              "required": ["entity_id", "label", "value"]
            },
            "description": "传感器面板，最多 6 条。按房间分组，温度/湿度相邻显示。",
            "maxItems": 6
          },
          "network_panel": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "source": {
                  "type": "string",
                  "description": "数据来源，如 unifi 或 ha"
                },
                "label": {
                  "type": "string",
                  "description": "显示标签，如"WAN 状态""
                },
                "value": {
                  "type": "string",
                  "description": "显示值"
                },
                "status": {
                  "type": "string",
                  "description": "状态标识，如 ok/warning/error"
                },
                "detail": {
                  "type": "string",
                  "description": "详细信息"
                }
              },
              "required": ["source", "label", "value", "status"]
            },
            "description": "网络面板，最多 6 条。",
            "maxItems": 6
          },
          "events_panel": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "time": {
                  "type": "string",
                  "description": "事件时间，如"10:10""
                },
                "text": {
                  "type": "string",
                  "description": "事件描述"
                },
                "level": {
                  "type": "string",
                  "description": "事件级别：info/warning/alert"
                }
              },
              "required": ["time", "text", "level"]
            },
            "description": "事件面板，最多 6 条。按时间倒序排列。",
            "maxItems": 6
          },
          "summary": {
            "type": "array",
            "items": {
              "type": "string",
              "maxLength": 20
            },
            "description": "1-3 条摘要，每条不超过 20 字，概括当前整体情况。",
            "minItems": 1,
            "maxItems": 3
          }
        },
        "required": ["sensor_panel", "network_panel", "events_panel", "summary"],
        "additionalProperties": false
      }
    }
  }
]
```

### Fast-Reply Tool Definitions（轻量刷新专用）

```
================================================
以下为轻量刷新使用的简化版（无 LLM Agent 参与）
================================================

轻量刷新不使用 LLM，直接由 refresh_lightweight.py 执行：
1. 从上一轮 final_output 提取 entity_id 列表
2. 对每个 entity_id 调用 HA /api/states 重拉数值
3. 对 UniFi 重拉 network health 和 events
4. 保持原有布局、summary 不变
5. 调用 DisplayClient.render(mode="partial")
```

### Tool Result 返回格式

```
# get_room_status 返回
{
  "room": "客厅",
  "entities": [
    {
      "entity_id": "sensor.miaomiaoc_...temp",
      "label": "客厅温度",
      "type": "temperature",
      "state": "28.2",
      "attributes": {
        "friendly_name": "客厅温度",
        "device_class": "temperature",
        "unit_of_measurement": "°C"
      }
    },
    {
      "entity_id": "climate.ke_ting_kong_diao",
      "label": "客厅空调",
      "type": "climate",
      "state": "cool",
      "attributes": {
        "friendly_name": "客厅空调",
        "hvac_action": "cooling",
        "current_temperature": 23,
        "temperature": 22,
        "fan_mode": "medium",
        "preset_mode": "none",
        "swing_mode": "off",
        "hvac_modes": ["auto", "cool", "dry", "fan_only", "heat", "off"]
      }
    }
  ]
}

# get_trend 返回
{
  "entity_id": "climate.ke_ting_kong_diao",
  "hours_back": 2,
  "current": 23,
  "min": 22.5,
  "max": 24.0,
  "avg": 23.2,
  "trend": "→",
  "delta": 0,
  "samples": [
    {"time": "2026-06-05T10:00:00", "value": 23.0},
    {"time": "2026-06-05T11:00:00", "value": 23.0},
    {"time": "2026-06-05T12:00:00", "value": 23.0}
  ]
}

# get_events 返回
[
  {"time": "10:10", "text": "书房空调已关闭", "level": "info", "source": "ha"},
  {"time": "09:41", "text": "书房空调设为制冷 目标26°C", "level": "info", "source": "ha"},
  {"time": "09:30", "text": "客户端 iPhone 连接 客厅AP", "level": "info", "source": "unifi"}
]

# get_network_health 返回
{
  "wan": {
    "status": "ok",
    "ip": "<public-wan-ip>",
    "latency_ms": 9,
    "tx_bps": 45191,
    "rx_bps": 8858,
    "uptime_days": 6.1,
    "cpu_pct": 12,
    "mem_pct": 22
  },
  "wlan": {
    "users": 34,
    "guests": 5,
    "aps_adopted": 4,
    "aps_disconnected": 0
  }
}

# get_wifi_environment 返回
{
  "own_aps": [
    {"name": "客厅AP", "channel_2g": 6, "channel_5g": 149, "tx_power": 20, "channel_width": 80}
  ],
  "rogue_aps": {
    "total": 441,
    "by_channel": {"1": 168, "6": 104, "11": 117},
    "strong_interferers": [
      {"essid": "HUAWEI-802", "channel": 1, "signal_dbm": -63}
    ]
  },
  "assessment": "2.4GHz 极度拥塞（ch1/6/11 均>100个AP），建议客户端优先使用 5GHz"
}

# get_client_status 返回
{
  "total": 39,
  "avg_signal_dbm": -53,
  "weak": [],
  "distribution": {"客厅AP": 15, "主卧AP": 10, "书房AP": 8, "客卧AP": 6}
}
```

### Orchestrator 伪代码

```python
class Orchestrator:
    def run(self) -> FinalOutput:
        # 1. 构建首轮 messages
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self.snapshot}
        ]

        tools = self.tool_registry.get_openai_tool_defs()  # OpenAI 格式

        # 2. Agent Loop
        for round in range(self.max_rounds + 1):
            response = self.llm.chat(messages, tools=tools)

            if not response.tool_calls:
                break  # LLM 选择不调用工具 → 结束

            # 截断至 1 个工具调用
            tool_call = response.tool_calls[0]

            # 配额检查
            if self.tool_registry.is_exhausted(tool_call.function.name):
                messages.append(self._build_quota_exhausted_msg(tool_call.function.name))
                continue

            # 执行工具
            result = self.tool_registry.execute(tool_call.function.name, tool_call.function.arguments)
            self.tool_registry.increment(tool_call.function.name)

            # 配额耗尽后从工具列表中移除
            if self.tool_registry.is_exhausted(tool_call.function.name):
                tools = [t for t in tools if t["function"]["name"] != tool_call.function.name]

            # 追加到对话
            messages.append({"role": "assistant", "content": None, "tool_calls": [tool_call]})
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result, ensure_ascii=False)})

            # 预检查：如果 LLM 调用了 final_output，直接提取返回
            if tool_call.function.name == "final_output":
                return json.loads(tool_call.function.arguments)

        raise RuntimeError("Agent loop exited without final_output")
```

---

## V1 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| V1 | 2026-06-05 | 初始设计：含系统提示词、快照模板、7 工具定义（含 tools_per_round=1 约束）、Tool Result 格式、Orchestrator 伪代码 |
| V1.1 | 2026-06-05 | 提示词外部化：所有 LLM 提示词移至 `config/prompts.yaml`，通过 `lib/prompts.py` 加载。添加 `InteractionLog`（三层日志：console 摘要 + JSONL 完整记录 + provider 请求/响应日志）。格式校验修复环（_execute_with_retry + _try_extract_json） |
| V1.2 | 2026-06-05 | 移除 `get_network_health` 工具（快照已含网络概览，工具与快照冗余）。工具矩阵 6+1 → 5+1。网络信息仍保留在首轮快照中供 LLM 参考 |

---

## V2 — 职责重构（2026-06-05）

### 核心变更

| 维度 | V1 | V2 |
|------|----|----|
| LLM 职责 | 控制 sensor/network/events/summary 四面板 | **仅控制 sensor_panel + summary** |
| tools_per_round | 1 | **2** |
| max_rounds | 6 | **3**（最后一轮仅 final_output） |
| summary 数量/字数 | 1-3 条，≤20 字 | **固定 3 条，≤50 字** |
| sensor_panel 必填 | entity_id + label + value | **label + value** |
| 网络面板 | LLM 生成 | **系统自动（lib/network_panel.py）** |
| 事件面板 | LLM 生成 | **系统自动** |
| 分析框架 | 无 | **现状-趋势-建议**三段式 |
| 话题去重 | 无 | **工作记忆「近期摘要参考」** |
| 温湿度合并 | 快照中展示 | LLM 输出也用合并值 |

### V2 系统提示词（最终版）

```
你是家庭环境仪表盘的智能体。你需要进行适当深度的分析，最终调用 final_output 提交仪表盘内容。

## 工作流程

1. 首轮快照已包含实体目录、当前状态、网络状态和近期事件。
2. 快照只给了你表面数据，你需要深挖：查看温度趋势（get_trend）、
   查询房间完整状态（get_room_status）、了解 WiFi 环境（get_wifi_environment）、
   客户端质量（get_client_status）等。
3. 不要只看快照就下结论。比如高温房间可能是空调故障、降温需要看趋势是↑还是↓。
4. 每轮可以调用 1-2 个工具。2 个工具应该是逻辑互补的（比如查客厅状态 + 趋势），不是随意的。
5. 最终必须调用 final_output。

## 工具调用约束

- 每轮可调用 1-2 个工具。如果生成超过 2 个，只执行前 2 个，其余丢弃。
- 每种工具的调用次数受全局配额限制。配额耗尽后该工具不可再调用。

## 你的职责

1. 从快照中选择最重要的传感器展示在 sensor_panel 中（不超过 6 条）
2. 每次刷新只选一个最感兴趣的话题深度分析，输出 3 条 summary

## 分析方法

每次刷新聚焦一个话题（温度/网络/事件等），输出 3 条 summary：
  第 1 句：总体概括 — 全屋当前的整体情况，风趣幽默
  第 2 句：选定话题深挖 — 包含具体数据和趋势（↑↓→），体现你做了深度分析
  第 3 句：建议或预测 — 基于分析给出的行动建议或趋势预判

## 话题选择

每次刷新选一个方向深挖。快照末尾有「近期摘要参考」列出了最近几轮的关注点，
你必须避开这些已说过的话题，选一个不同的角度：
  · 温度热点 — 哪个房间异常？趋势如何？空调是否匹配？
  · 网络环境 — WiFi 干扰？客户端信号？设备增减？
  · 安全事件 — 门锁？异常活动？

## 输出规范（严格遵循，否则会被拒绝）

- sensor_panel：不超过 6 条，label 必须与快照逐字一致，value 使用快照已合并的值
- 只放传感器实体（温湿度/空调/灯/窗帘），WiFi、客户端等网络信息不要放
- summary：固定 3 条字符串，每条 <=50 字。格式：概括 -> 深挖 -> 建议
- 不要使用 emoji 表情符号
- 网络面板和事件面板由系统自动生成，你不用管
```

### V2 final_output 工具定义

```json
{
  "type": "function",
  "function": {
    "name": "final_output",
    "description": "提交仪表盘最终内容。sensor_panel 为传感器列表，summary 为摘要字符串列表。",
    "parameters": {
      "type": "object",
      "properties": {
        "sensor_panel": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "label": {"type": "string"},
              "value": {"type": "string"},
              "trend": {"type": "string", "enum": ["↑", "↓", "→"]},
              "remark": {"type": "string"}
            },
            "required": ["label", "value"]
          },
          "maxItems": 6
        },
        "summary": {
          "type": "array",
          "items": {"type": "string", "maxLength": 50},
          "minItems": 3,
          "maxItems": 3
        }
      },
      "required": ["sensor_panel", "summary"],
      "additionalProperties": false
    }
  }
}
```

### V2 变更路径

| # | 触发 | 变更 |
|---|------|------|
| 1 | 去掉网络/事件面板控制权 | final_output 移除 network_panel/events_panel 参数 |
| 2 | 去掉 entity_id | sensor_panel required: [entity_id,label,value] -> [label,value] |
| 3 | LLM 输出 dict 非字符串 | summary 校验增加 isinstance(s, str) |
| 4 | summary 超长 | maxLength: 30 -> 50 |
| 5 | emoji 乱码 | 提示词+工具描述禁止 emoji |
| 6 | 话题重复 | 新增「近期摘要参考」工作记忆，要求避开 |
| 7 | 缺少趋势 | 要求深挖，摘要框架改为概括->深挖->建议 |
| 8 | 温湿度拆分 | 快照+LLM输出都用合并值 |
| 9 | 工具/轮太紧 | tools_per_round: 1->2, max_rounds: 6->3 |
| 10 | 网络面板不统一 | 抽取公共模块 lib/network_panel.py |
| 11 | 日志截断 | 去掉 _truncate_messages，完整记录 |
| 12 | reasoning 缺失 | InteractionLog 增加 reasoning_content 和 tool_calls_summary |

---

## V3 — DPI 工具扩展与纯数据重构（2026-06-06）

### 核心变更

| 维度 | V2 | V3 |
|------|----|----|
| 工具数量 | 5 + final_output | **8 + final_output** |
| 工具输出风格 | 含分析结论 | **纯数据，零结论** |
| 工具总输出 | ~21K chars | **~10K chars (-53%)** |
| `get_client_status` | 39 设备全量+分析 | **top5 默认 / mac 单查** |
| `get_room_status` | 全实体+全属性 | **有价值实体+精简 attrs** |
| 快照内容 | 实体+网络+事件 | **+DPI 流量分析段** |

### V3 新增工具

| # | 工具 | 描述 |
|---|------|------|
| 6 | `get_traffic_analysis` | 获取家庭网络流量分析，包含 TOP 应用流量排行、分类分布。scope='site' 全站或 scope='device' + mac 单设备 |
| 7 | `get_device_inventory` | 获取设备盘点：总数/在线/离线/有线/无线、24h 新设备、7d 长期离线设备。filter='new'/'offline'/'online' |
| 8 | `get_network_alarms` | 获取网络告警列表：分类计数、近期告警详情、WAN 切换按小时分布、ISP 定时重拨说明 |

### V3 更新的工具描述

```json
{
  "name": "get_client_status",
  "description": "获取 WiFi/有线客户端连接状态。默认返回流量最高的 5 个设备；传入 mac 参数则仅返回指定设备的详细信息。",
  "parameters": {
    "properties": {
      "mac": {"type": "string", "description": "设备 MAC 地址（格式 xx:xx:xx:xx:xx:xx），指定则只返回该设备。不传则返回流量 TOP5。"}
    }
  }
}
```

```json
{
  "name": "get_room_status",
  "description": "获取指定房间有意义的实体状态和属性（传感器、空调、窗帘、门磁、灯、播放器）。过滤开关/按钮/配置等无关实体。",
  "parameters": {
    "properties": {
      "room_name": {"type": "string", "description": "房间名", "enum": [...]}
    },
    "required": ["room_name"]
  }
}
```

```json
{
  "name": "get_wifi_environment",
  "description": "获取 WiFi 环境分析，包括自家 AP 列表及信道配置、周围干扰 AP 列表及信号强度、信道拥塞评估。",
  "parameters": {
    "properties": {
      "band": {"type": "string", "enum": ["2g", "5g", "all"], "description": "频段过滤"}
    }
  }
}
```

```json
{
  "name": "get_traffic_analysis",
  "description": "获取家庭网络流量分析，包括：TOP 应用流量排行（按下载/上传）、流量分类分布。scope='site' 全站或 scope='device'+mac 单设备。",
  "parameters": {
    "properties": {
      "scope": {"type": "string", "enum": ["site", "device"], "description": "分析范围"},
      "mac": {"type": "string", "description": "设备 MAC 地址（scope=device 时必填）"}
    }
  }
}
```

```json
{
  "name": "get_device_inventory",
  "description": "获取设备盘点信息，包括：总数/在线/离线、24h 新设备列表、7d 长期离线设备。filter='new'/'offline'/'online'/'all'。",
  "parameters": {
    "properties": {
      "filter": {"type": "string", "enum": ["all", "new", "offline", "online"], "description": "过滤条件"}
    }
  }
}
```

```json
{
  "name": "get_network_alarms",
  "description": "获取网络告警列表，包括：各类告警的累计总数和近期发生次数、WAN 切换事件的时间分布、近期告警详情。",
  "parameters": {
    "properties": {
      "hours_back": {"type": "number", "description": "回溯小时数，默认 24", "minimum": 1, "maximum": 168}
    }
  }
}
```

### V3 快照模板变更

```
## 流量分析                 ← 新增段
全站总流量: 390GB
TOP 10 应用:
  未识别流量: ↓112.9GB ↑27.1GB (56台设备)
  HTTP大流量: ↓72.8GB ↑33.6GB (50台设备)
  ...
当前活跃设备 TOP 10（会话流量）:
  iPhone: ↓306MB ↑288MB WiFi 信号=-52dBm 在线45min
  ...
```

### V3 工具返回格式变更

```
# get_client_status 返回（V2 → V3）
V2: {total, avg_signal_dbm, weak: [...], distribution: {...}}
V3: {total, top_clients: [{hostname, ip, mac, signal_dbm, channel, band, ap, ...} ×5]}

# get_client_status(mac) 返回（V3 新增）
V3: {total, client: {hostname, ip, mac, signal_dbm, ...}}

# get_room_status 返回（V2 → V3）
V2: 全 entities（含 switch/button）+ 全 attributes
V3: 仅 sensor/climate/cover/light/media_player + 按 type 精简 attributes

# get_wifi_environment 返回（V2 → V3）
V2: {own_aps, rogue_aps, assessment: "2.4GHz 极度拥塞..."}
V3: {own_aps, rogue_aps}  ← 移除 assessment

# get_network_alarms 返回（V3 新增）
V3: {period_hours, total_alarms, alarms_in_period, alarm_counts,
     recent_alarms, wan_transition_total, wan_transition_by_hour,
     note: "WAN 每日定时重拨..."}

# get_traffic_analysis 返回（V3 新增）
V3: site → {top_apps, categories, total_traffic_gb}
    device → {device_mac, total_traffic_kb, top_apps}

# get_device_inventory 返回（V3 新增）
V3: {total_devices, online_devices, wired_devices, wireless_devices,
     new_devices_24h, long_offline_7d, [new_devices], [long_offline]}
```

### V3 变更路径

| # | 触发 | 变更 |
|---|------|------|
| 1 | UniFi DPI 端点发现 | 新增 `get_traffic_analysis`（site + device 两种 scope） |
| 2 | UniFi alluser 端点发现 | 新增 `get_device_inventory`（新设备检测 + 离线追踪） |
| 3 | UniFi alarm 端点发现 | 新增 `get_network_alarms`（WAN 切换时间分布 + ISP 重拨说明） |
| 4 | WAN 切换 313 次分析 | `get_network_alarms` 添加 note 说明早晚 6 点属正常 PPPoE 刷新 |
| 5 | 工具输出膨胀（21K chars） | `get_client_status` 改为 top5/mac 模式，减少 87% |
| 6 | 分析结论不属于工具 | 移除 4 个工具的 assessment/anomalies/device_type 字段 |
| 7 | 灯/开关 attrs 冗余 | `get_room_status` 按 type 白名单精简，off 灯 attrs 为空 |
| 8 | 快照缺少 DPI 上下文 | 快照新增「流量分析」段（TOP10 应用 + 活跃设备 TOP10） |
| 9 | token 消耗不可见 | InteractionLog 记录 API usage，OPS 面板展示上次 Token 消耗 |

---

## V4 — 工具调用方向约束（2026-06-06）

### 核心变更

| 维度 | V3 | V4 |
|------|----|----|
| 工具调用选择 | 可调用任意工具 | **仅调用与选定方向相关的工具** |
| LLM 方向选择 | 隐式（不强制声明） | **显式声明再调用** |

### 变更触发

观察到 LLM 经常在同一轮混合两个无关方向（如同时查网络告警和温度趋势），导致工具浪费、对话历史膨胀。

### 新增约束

在 `config/prompts.yaml` 的「工具调用约束」段新增：

> **只调用与你当前选定方向相关的工具**。如果你在本轮选择深挖「温度热点」，就不要调用 get_wifi_environment、get_client_status、get_traffic_analysis 等与温度无关的工具。如果你选择深挖「网络环境」，就不要调用 get_room_status、get_trend（温度趋势）。每个工具调用必须有明确的、与选定方向直接相关的问题驱动，而不是随意调用。

### Token 消耗对比

| 运行 | 方向 | 轮数 | 工具调用 | 总 Token |
|------|------|------|---------|---------|
| 修改前 `140621` | 混合（网络告警+温度趋势同轮） | 4 | get_network_alarms, get_trend, get_client_status, get_device_inventory | **48,607** |
| 历史 `133022` | 偏网络但松散 | 5 | get_client_status, get_events, get_device_inventory×2, get_network_alarms | **37,773** |
| 修改后 `141155` | **纯网络（聚焦）** | **3** | get_wifi_environment, get_client_status, get_device_inventory, get_network_alarms | **21,102** |

**Token 节省：-57%（vs 混杂方向）-44%（vs 历史同类型运行）**

节省主要来自：
1. **轮数减少**：4-5 轮 → 3 轮（方向聚焦后决策路径更短）
2. **prompt token 累计更少**：方向聚焦→消息历史增长慢→每轮重复传输的上下文更少
3. **无浪费调用**：不再出现同轮 invalidation（看了告警又看趋势、两个方向都不深入）

### 行为变化

| 维度 | 修改前（V3） | 修改后（V4） |
|------|------------|------------|
| LLM 声明方向 | 偶尔提及，不强制 | **明确说"这次我来深挖 XX"** |
| 工具聚焦度 | 50% 轮次有混杂 | **100% 同方向** |
| 平均轮数 | ~3.8 | **3.0** |
| 平均总 Token | ~43,000 | **~21,000** |

### V4 变更路径

| # | 触发 | 变更 |
|---|------|------|
| 1 | 同一轮混查网络告警+温度趋势，浪费工具调用 | 新增「方向约束」：只调用与选定方向相关的工具 |

