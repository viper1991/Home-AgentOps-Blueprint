# 辅助工具脚本

本目录存放开发调试用的辅助工具。所有脚本需**从项目根目录运行**。

## 工具列表

| 脚本 | 用途 | 用法 |
|------|------|------|
| `check_wan.py` | UniFi WAN 双线诊断 (USG/UDM) | `python scripts/check_wan.py` |
| `show_reasoning.py` | LLM 推理日志查看 | `python scripts/show_reasoning.py` |
| `v_last.py` | 快速查看最新仪表盘输出 | `python scripts/v_last.py` |
| `test_ha_ws_explore.py` | HA WebSocket 事件探路 | `HA_TOKEN=xxx python scripts/test_ha_ws_explore.py` |

## 依赖

- `check_wan.py`: 需要 `config/config.yaml` 正确配置
- `show_reasoning.py`: 需要 `logs/interactions/` 目录存在
- `v_last.py`: 需要 `outputs/` 目录存在
- `test_ha_ws_explore.py`: 需要 `pip install aiohttp`，通过环境变量传入凭证
