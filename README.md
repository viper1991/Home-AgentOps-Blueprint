<p align="center">
  <h1 align="center">Home-AgentOps-Blueprint (HAB)</h1>
  <p align="center">
    <b>基于大模型 Agent 治理架构的物理环境智能态势感知与 Ops 运维系统</b>
  </p>
  <p align="center">
    Architecture: Hybrid-Refresh Agent &nbsp;|&nbsp; Hardware: Raspberry Pi + E-Ink SPI &nbsp;|&nbsp; LLM Cost: ~¥0.005 / Heavy Run
  </p>
  <p align="center">
    Stack: Claude Code & DeepSeek V4
  </p>
  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
    <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/e--paper-4.26%22%20800%C3%97480-green" alt="E-Paper">
  </p>
</p>

---

## 开发者引言

本项目由一名 Java 老兵进行系统架构治理设计。由于作者完全不会 Python，全量生产级代码（包含基于 Tailwind 的 Web 端 Ops 运维服务与组件解耦）均由 Claude Code 搭配 DeepSeek-V4 (pro+flash) 在两天内结对编程高效完成。

本项目证明了：**在 AI 时代，人类的架构审美、特征工程剪枝与边界约束能力，才是构建复杂智能体系统的核心生产力。**

---

## 项目愿景与核心痛点

当前智能家居（如 Home Assistant）的自动化高度依赖静态的 `if-else` 规则或固定看板。当传感器增多、网络环境复杂时，传统的平铺式 Dashboard 会带来极高的**认知载荷**。用户往往需要在一堆没有变化的数值中，肉眼寻找异常。虽然有些平台如HA本身也支持LLM集成，但其高度依赖于平台能力本身，作为极客的玩具来说，略显笨重。

**本项目彻底颠覆了这种传统模式。** 它利用 LLM Agent（智能体）充当家庭的"首席信息官"，将 Home Assistant（家电与环境）和 UniFi（射频与拓扑）彻底抽象为大模型的**工具矩阵（Tool Matrix）**。大模型每小时自主决定调用哪些工具探索家里的蛛丝马迹，最终将复杂的物理世界数据提炼成极具"人情味"的三段式大白话总结，并优雅地推送到一块低功耗、高质感的电子墨水屏上。

<img width="300" height="200" alt="demo2" src="https://github.com/user-attachments/assets/1615423a-7e9f-4161-8db8-ca7ac1d3eeec" />
<img width="300" height="200" alt="demo1" src="https://github.com/user-attachments/assets/6f1e5e45-9ee5-4a1e-8254-9f3f6d45b556" />
<img width="300" height="400" alt="demo3" src="https://github.com/user-attachments/assets/69e78ef0-c700-4f85-947d-bac3166f70cc" />

---

## 为什么"开源设计，弱化代码"？

当前开源社区陷入了一种浮躁的怪圈：一端是大量"一键部署、复制粘贴"的 Demo，用户沦为机械的运行机器；另一端是键盘侠们对着任何接了大模型 API 的项目高喊"套壳"。

我们认为，**在 AI 时代，具体的代码语法（Python / Java / Go）已经降维成了最廉价的"纯粹执行"，人类的核心生产力已经全面回归到：系统架构审美、特征工程剪枝、边界约束以及系统治理能力。**

因此，本项目的 Python 源码仅供参考。我们提供的是一套经过真实物理世界（树莓派 + 墨水屏 + HA + UniFi）验证的 **工业级 Agent 治理蓝图（Blueprint）**。

**我们鼓励你：**

1. 复制本仓库中的**设计思想、数据清洗策略与 Prompt 契约**
2. 将这套"架构灵魂"喂给你自己的 AI（Claude / DeepSeek / GPT）
3. 尝试你最擅长或从未尝试过的技术栈（Java / Go / Rust / Node.js / Python），**让 AI 做你的手脚**，亲自创造出属于你自己的、独一无二的智能体代码

> **当前仓库中的 Python 代码只是由 AI 生成的一种实现示例，用于验证架构可行性。不必纠结代码本身的完美——真正的价值在于设计本身。**

---

## 核心架构与"防御性工程"设计

为了杜绝目前绝大多数开源 Agent 项目存在的"Token 爆炸"、"陷入无限规划死循环"以及"运行成本不可控"等顽疾，本项目注入了工业级的系统治理思维，采用了**混合两级刷新与工作记忆剪枝架构**：

### 1. 轻重刷新双引擎解耦 (Hybrid-Refresh)

| | 重量级刷新 (Heavyweight) | 轻量级刷新 (Lightweight) |
|---|---|---|
| **触发** | Cron 定时（如每小时） | Cron 高频（如每 5 分钟） |
| **Token 消耗** | ~26,000 Token / 次 | 零 |
| **LLM** | 完整 Agent Loop，多轮工具调用 | 不参与 |
| **sensor_panel** | LLM 自主选择 ≤6 条传感器 | 按上轮 label 反查 entity_catalog |
| **summary** | LLM 生成三段式总结 | 保留不变 |
| **渲染** | 全刷（~4s） | 局部刷（~0.5s） |
| **工作记忆** | 保存到 outputs/ | 不保存 |

### 2. 物联网上下文特征工程剪枝

如果将 Home Assistant 原生拉取的全部状态直接丢给大模型，单次将产生超过 500KB 的冗余 JSON 噪音，极易导致大模型幻觉与费用暴增。本项目实现了极致的白名单过滤与动态裁剪：

| 清洗维度 | 处理策略 | 典型效果 |
|---------|---------|---------|
| 实体目录本地化 | 通过 `entity_catalog.yaml` 静态约束，不靠运行时 API 漫无目的发现 | 1090 个实体 → 聚焦核心传感器 |
| Domain 类型过滤 | 直接拦截并剔除无仪表盘展示价值的 `number`, `select`, `button` | 实体体积缩减约 40% |
| Type→Attrs 白名单 | 对 `climate`, `light`, `cover` 实施属性裁剪，灯关闭时其 14 个 `effects` 字段直接清空 | 单次工具返回从 10,795 chars 骤降至 1,132 chars |

### 3. 工具配额拦截与硬熔断 (Quota & Circuit Breaker)

大模型进入 Agent 状态后，极易对某些异常数据产生"执念"，导致在多轮 Loop 中反复调用同一工具。本项目在代码层面实施了严格的**配额拦截器（Quota Tracker）**：

- `max_rounds: 3` 顶级硬熔断，第 4 轮强制收敛并调用 `final_output`
- 工具级配额限制：如 `get_room_status` 单次任务最多允许调用 3 次；历史趋势查询 `get_trend` 强制硬编码截断最大 4 小时历史，阻断长上下文膨胀

---

## AgentOps 运维后端与可观测性

不同于绝大多数"运行全黑盒"的套壳项目，本项目内置了一个完整的 **AgentOps 可观测性看板（基于 Tailwind 暗黑科技风）**，让智能体的每一步思考都有迹可循：

- **Token 账单原子化监控**：直观显示单次 Agent 交互所消耗的精确 Token 数（典型重量级多轮交互消耗为 ~26,000 Token，折合人民币仅约 ¥0.005）
- **思维链（Thinking Process）可视化**：实时将 Agent 每轮的中间推理状态（Thought）和耗时持久化并渲染到前端日志中
- **远程屏幕预览（Remote Canvas Preview）**：后端通过守护进程同步捕捉当前 Canvas 像素，在 Web 端提供严格对齐的 1:1 预览图。允许开发者坐在电脑前直接进行 Prompt 远程调优，彻底告别频繁跑向物理屏幕查看对齐的痛苦

---

## 驯化日志摘录：真实的智能体灵性

以下为系统运行中，大模型 Agent 自主发现家庭无线射频冲突后，在墨水屏上输出的真实内容。它展现了智能体在严格限制下（无 Emoji、严格 50 字、概括→深挖→建议三段式）所爆发出的高价值态势感知能力：

```
[传感器面板]
室外温湿度: 25.8°C / 77%    |  客厅空调: 24°C 关机
客厅温湿度: 25.8°C / 67%    |  书房温湿度: 26.7°C / 70.5%

[AI 态势感知摘要]
1. 全屋温湿度一片祥和，但 WiFi 信道在打群架。
2. 2.4G 信道 1 挤了 170 个邻居，客厅书房客卧三 AP 扎堆内耗。
3. 建议客厅 AP 切到信道 6 或更冷门的信道减少同频干扰。
```

---

## 快速开始

### 硬件需求

- Raspberry Pi（任意带 GPIO 型号，测试于 3B+）
- Waveshare 电子墨水屏（当前适配 4.26inch 800×480，可适配其他型号）
- SPI 连接线

### 部署步骤

```bash
# 1. 安装系统依赖
sudo apt-get install -y python3-pip python3-pil fonts-wqy-microhei
sudo raspi-config nonint do_spi 0   # 启用 SPI

# 2. 克隆项目
git clone https://github.com/viper1991/Home-AgentOps-Blueprint.git
cd Home-AgentOps-Blueprint
pip install -r requirements.txt --break-system-packages

# 3. 配置
cp config/config.yaml.example config/config.yaml
cp config/entity_catalog.yaml.example config/entity_catalog.yaml
cp config/prompts.yaml.example config/prompts.yaml
# 编辑 config.yaml: 填入 HA / UniFi 地址和凭证
# 编辑 entity_catalog.yaml: 填入你的房间和实体

# 4. 设置 API Key
export DEEPSEEK_API_KEY=sk-xxxxx
echo 'export DEEPSEEK_API_KEY=sk-xxxxx' >> ~/.bashrc
# 注意：sk-xxxxx 仅为占位示例，请替换为你的真实 API Key

# 5. 启动显示服务
sudo systemctl enable --now hab-display

# 6. 运行刷新测试
python3 refresh_lightweight.py    # 初始化显示
python3 refresh_heavyweight.py    # LLM Agent 全量分析

# 7. (可选) 启动运维面板
python3 ops_server.py --port 8080
# 浏览器访问 http://<pi-ip>:8080
```

### 设置 Crontab

```cron
# 重型刷新 — 每小时第 5 分钟（22:00-08:00 休眠跳过）
5 * * * * cd /home/<pi-user>/hab && python3 refresh_heavyweight.py >> logs/cron.log 2>&1

# 轻型刷新 — 每 5 分钟，滞后重型 2 分钟（22:00-08:00 休眠跳过）
2,7,12,17,22,27,32,37,42,47,52,57 * * * * cd /home/<pi-user>/hab && python3 refresh_lightweight.py >> logs/cron.log 2>&1

# 墨水屏夜间关闭 / 早晨唤醒（延长硬件寿命）
0 22 * * * sudo systemctl stop hab-display
30 7 * * * sudo systemctl start hab-display
```

---

## 工具矩阵（Agent Functions）

LLM Agent 通过这些工具探索家庭环境：

| # | 工具 | 功能 | 配额 |
|---|------|------|------|
| 1 | `get_room_status` | 按房间获取实体完整状态 | ≤3 次 |
| 2 | `get_trend` | 单实体历史趋势分析（≤4h） | ≤3 次 |
| 3 | `get_events` | 合并去噪 HA logbook + UniFi 事件 | 不限 |
| 4 | `get_wifi_environment` | WiFi 信道拥塞与干扰分析 | 不限 |
| 5 | `get_client_status` | 客户端连接质量分析 | 不限 |
| 6 | `get_traffic_analysis` | 全站 / 单设备 DPI 流量画像 | ≤2 次 |
| 7 | `get_device_inventory` | 设备盘点 + 新设备检测 | ≤1 次 |
| 8 | `get_network_alarms` | WAN / AP 稳定性评估 | ≤1 次 |
| 9 | `final_output` | 提交仪表盘内容（sensor_panel + summary） | — |

---

## 项目结构

```
hab/
├── display_server.py              # Display 守护进程（独占物理 GPIO 与画布渲染）
├── refresh_heavyweight.py         # 重量级 Cron：Agent 多轮推理循环 → 全量全刷
├── refresh_lightweight.py         # 轻量级 Cron：零 Token 动态反查 → 静态局刷
├── ops_server.py                  # Web 运维端：AgentOps 监控 + 远程屏幕同步
├── requirements.txt               # Python 依赖
│
├── lib/                           # 共享库
│   ├── config.py                  # YAML 配置加载
│   ├── prompts.py                 # 提示词加载器
│   ├── network_panel.py           # 网络面板公共模块（三层共用）
│   ├── interaction_log.py         # LLM 交互日志（JSONL）
│   ├── tool_counter.py            # 工具调用配额计数器
│   ├── working_memory.py          # 工作记忆（最近 10 次输出）
│   ├── dpi_apps.py                # DPI 应用/分类 ID 映射表
│   │
│   ├── clients/                   # 底层协议通信客户端
│   │   ├── ha_client.py           # Home Assistant REST API
│   │   └── unifi_client.py        # UniFi REST API
│   │
│   ├── tools/                     # 抽象工具矩阵（Base ABC 基类）
│   │   ├── base.py                # Tool 基类 + ToolRegistry + 配额追踪
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
│   ├── agent/                     # Agent 引擎
│   │   ├── snapshot.py            # 首轮快照构建器
│   │   └── orchestrator.py        # Agent Loop 引擎（1-2 工具/轮）
│   │
│   ├── llm/                       # LLM 抽象层
│   │   ├── provider.py            # LLMProvider 接口
│   │   └── deepseek.py            # DeepSeek 实现（OpenAI SDK）
│   │
│   └── display/                   # 渲染栈
│       ├── protocol.py            # DisplayClient（Socket 协议）
│       ├── renderer.py            # Layout + Widget 渲染引擎
│       └── epaper_driver.py       # Waveshare EPD 封装
│
├── config/                        # 配置（gitignored，含 .example 模板）
│   ├── config.yaml                # 全局配置
│   ├── config.yaml.example
│   ├── entity_catalog.yaml        # 实体目录（手动维护）
│   ├── entity_catalog.yaml.example
│   ├── prompts.yaml               # LLM 提示词
│   └── prompts.yaml.example
│
├── vendor/                        # 第三方依赖
│   ├── README.md
│   └── waveshare_epd/             # Waveshare 官方 Python 驱动
│
├── docs/                          # 文档
│   ├── system_design.md           # 系统设计文档（原 CLAUDE.md）
│   ├── display_server_architecture.md
│   ├── display_server_manual.md
│   └── ops.md                     # 部署运维手册
│
├── research/                      # 研究过程记录
│   ├── README.md                  # 研究文档阅读指南
│   ├── RESEARCH_LOG.md            # 工具矩阵 8 阶段推导日志
│   └── prompt_log.md              # 提示词演进日志（V1→V4）
│
├── scripts/                       # 辅助脚本（开发/调试用）
│   ├── README.md
│   ├── check_wan.py               # WAN 双线诊断
│   ├── show_reasoning.py          # LLM 推理日志查看
│   ├── v_last.py                  # 最新输出快速查看
│   └── test_ha_ws_explore.py      # HA WebSocket 探路
│
├── fonts/                         # 中文字体（用户自备）
├── outputs/                       # 工作记忆（gitignored）
└── logs/                          # 运行时日志（gitignored）
```

---

## 设计原则

- **Agent 模式**：重量刷新将 HA 和 UniFi 抽象为"工具"，LLM 通过 function calling 自主决定调用策略
- **实体目录 = 本地配置**：实体定义不靠运行时 API 发现，而是手动维护在本地配置文件，行为可预期
- **纯实时，仅工作记忆**：不缓存任何 API 数据。仅保存最近 10 次 summary 作为工作记忆帮助 LLM 避开重复话题
- **单进程单责**：仅 `display_server.py` 操作 GPIO，其余进程通过 Socket 协议通信

---

## 扩展指南

### 新增工具

在 `lib/tools/` 下创建文件，继承 `Tool` ABC：

```python
from lib.tools.base import Tool

class MyTool(Tool):
    name = 'my_tool'
    description = '工具描述'
    parameters = {
        'type': 'object',
        'properties': {
            'param': {'type': 'string', 'description': '参数说明'},
        },
        'required': ['param'],
    }

    def execute(self, param: str) -> dict:
        # 工具逻辑
        return {'result': 'ok'}
```

在 `refresh_heavyweight.py` 的 `ToolRegistry()` 中注册即可。

### 新增 LLM Provider

1. 创建 `lib/llm/<provider>.py`，实现 `LLMProvider` ABC
2. 在 `refresh_heavyweight.py` 中切换
3. 更新 `config.yaml.example` 文档

### 适配其他墨水屏型号

1. 确保 `vendor/waveshare_epd/` 下存在对应型号的 Python 驱动
2. 修改 `lib/display/epaper_driver.py` 第 125 行的导入：`from waveshare_epd import epdXinXX as ws`
3. 修改 `config.yaml` 中 `epaper` 配置节

---

## 配置参考

### config.yaml

| 路径 | 说明 |
|------|------|
| `ha.url` | Home Assistant REST API 地址 |
| `ha.token` | HA 长期访问令牌 |
| `unifi.url` | UniFi Controller 地址 |
| `unifi.username` | UniFi 只读用户 |
| `llm.model` | DeepSeek 模型名 |
| `llm.api_key_env` | API Key 环境变量名 |
| `agent.max_rounds` | LLM 最大交互轮数 |
| `agent.tools_per_round` | 每轮最多工具调用数 |
| `display.daemon_port` | Display Server 端口（默认 5150） |
| `epaper.model` | 墨水屏型号（当前 `4in26`） |

### entity_catalog.yaml

手动维护室内设备清单：

```yaml
rooms:
  - name: 客厅
    entities:
      - { id: sensor.xxx_temp, label: 客厅温湿度, type: temperature }
      - { id: sensor.xxx_humid, label: 客厅温湿度, type: humidity }
      - { id: climate.xxx_ac, label: 客厅空调, type: climate }

snapshot_entities:
  - sensor.xxx_temp
  - sensor.xxx_humid
  - climate.xxx_ac
```

**温湿度合并技巧**：同一设备的温湿度传感器给相同的 label，显示时会自动合并为一行（如 `客厅温湿度 26°C / 60%`）。

---


## 贡献指南

欢迎贡献代码、反馈问题或提出功能建议。详见 [CONTRIBUTING.md](.github/CONTRIBUTING.md)。

---

## 安全

本项目需连接家庭内网的 Home Assistant 和 UniFi 控制器。安全相关信息见 [SECURITY.md](SECURITY.md)。

---

## 鸣谢

感谢 [Claude Code](https://claude.ai/code) 提供的无缝代码重构与工程执行力，感谢 [DeepSeek](https://deepseek.com) 提供的极具性价比的强悍 Function Calling 推理大脑。

AI 已经改变了软件工程的范式。只要你拥有扎实的架构设计思维，没有任何一门语言能够阻挡你创造属于自己的极客艺术品。

---

## 许可证

[MIT](LICENSE)
