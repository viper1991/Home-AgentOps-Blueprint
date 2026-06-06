# 字体

本目录存放墨水屏渲染所需的 TrueType/OpenType 字体。

## 提供字体

| 文件 | 来源 | 许可 |
|------|------|------|
| `wqy-microhei.ttc` | [WenQuanYi (文泉驿)](http://wenq.org/) | GPL 2+ / Apache 2.0 双授权 |

`wqy-microhei.ttc` 已随仓库分发，无需额外安装。在该字体无法满足需求时可自行替换。

## 替换为其他字体

`config/config.yaml` 中的 `font.name` 支持任意 `.ttf` / `.ttc` / `.otf` 中文字体，例如：

- **Source Han Sans SC**（思源黑体）— SIL Open Font License
- **Noto Sans CJK SC** — SIL Open Font License

替换步骤：

1. 将字体文件放入 `fonts/` 目录
2. 修改 `config/config.yaml` → `font.name` 为对应文件名

## 系统字体回退

如果 `fonts/` 目录为空或配置的字体不存在，渲染器会自动尝试以下系统路径（Pi）：

- `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`
- `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`
- `/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf`
- `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`

Raspberry Pi 用户可通过 `sudo apt install fonts-wqy-microhei` 将字体安装至系统路径。
