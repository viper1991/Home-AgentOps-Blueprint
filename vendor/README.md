# Vendor — 第三方库

此目录存放依赖的第三方代码。

## waveshare_epd

Waveshare 官方电子墨水屏 Python 驱动库。

- **来源**: [Waveshare e-Paper](https://github.com/waveshareteam/e-Paper)
- **路径**: `vendor/waveshare_epd/`
- **用途**: `lib/display/epaper_driver.py` 通过此库完成 SPI 驱动与墨水屏通信
- **许可证**: 参见原始仓库的协议

### 兼容型号

当前项目使用 `epd4in26` (4.26inch 800×480)，库内含多种型号驱动：

- epd4in26 (本项目的核心依赖)
- epd2in13 / epd1in54 等其他型号（保留以支持扩展）

### 更新

直接从 Waveshare 官方仓库同步 Python 库即可：

```bash
git clone https://github.com/waveshareteam/e-Paper.git
cp -r e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd vendor/
```
