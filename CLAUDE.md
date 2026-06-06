# CLAUDE.md — Claude Code 工作指引

面向 Claude Code 的项目上下文文件。首次进入项目时，自动加载此文件作为系统提示词的一部分。

---

## 项目概述

HAB (Home-AgentOps-Blueprint) 是一个运行在 Raspberry Pi 上的家庭信息仪表盘系统。通过 LLM Agent（DeepSeek）自主分析 Home Assistant 传感器数据 + UniFi 网络状态，生成三段式洞察报告，推送到 Waveshare 电子墨水屏。

## 工作准则

1. **修改代码前先读文档**。`docs/` 目录下有完整的设计文档和运维手册。不确定架构或数据流时，先查阅相关文档。
2. **配置是敏感信息**。`config/config.yaml` / `entity_catalog.yaml` / `prompts.yaml` 被 `.gitignore` 排除。永远不要在其中写入真实凭证或 token。
3. **Python 代码风格**：PEP 8，中文注释，`snake_case` 函数/变量，`PascalCase` 类名。
4. **只改你被要求改的**。不要顺手重构无关模块。

## 文档索引（按需查阅）

| 文档 | 路径 | 何时查阅 |
|------|------|---------|
| **系统设计** | `docs/system_design.md` | 理解整体架构、核心设计理念、工具矩阵、数据流 |
| **运维手册** | `docs/ops.md` | 部署、crontab、配置项、故障处理 |
| **Display Server 架构** | `docs/display_server_architecture.md` | 渲染器/Widget/墨水屏驱动细节 |
| **Display Server 运维** | `docs/display_server_manual.md` | Socket 协议、手动测试、systemd 管理 |
| **研究日志** | `research/` | 工具矩阵推导过程、提示词演进历史 |

## 关键架构约束

- **单进程单责**：仅 `display_server.py` 操作 GPIO/SPI，其余进程通过 `127.0.0.1:5150` Socket 通信
- **两级刷新**：`refresh_heavyweight.py`（LLM Agent，~4s 全刷） vs `refresh_lightweight.py`（无 LLM，~0.5s 局刷）
- **Agent 工具配额**：`lib/tools/` 下 8 个数据工具 + `final_output`。每种工具有全局调用次数限制，`max_rounds=4` 硬熔断
- **工作记忆**：最近 10 次 `final_output` 存入 `outputs/`，近 5 次 summary 传给 LLM 避重
- **LLM Provider**：当前仅 DeepSeek（`lib/llm/deepseek.py`），通过 OpenAI SDK 调用

## 常用路径速查

```
display_server.py          — 常驻守护进程
refresh_heavyweight.py     — 重量级刷新入口
refresh_lightweight.py     — 轻量级刷新入口
ops_server.py              — Web 运维面板 (Flask, port 8080)
lib/agent/orchestrator.py  — Agent Loop 引擎
lib/agent/snapshot.py      — 首轮快照构建器
lib/tools/                 — 工具矩阵（8 个数据工具 + final_output）
lib/clients/               — HA / UniFi REST API 客户端
lib/display/epaper_driver.py — Waveshare EPD 驱动封装
vendor/waveshare_epd/      — Waveshare 官方 Python 库
research/                  — 设计研究过程文档
```
