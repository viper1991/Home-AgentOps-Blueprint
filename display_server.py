#!/usr/bin/env python3
"""HAB Display Server — 墨水屏显示守护进程。

常驻后台，通过 TCP localhost:5150 接收 JSON 指令。
使用 Layout + Widget 架构渲染 800×480 位图并驱动 Waveshare 4.26" e-Paper。

支持指令:
  render {cmd, mode, data}  渲染并显示（mode=full|partial）
  clear   {cmd}              清屏
  sleep   {cmd}              深度休眠
  status  {cmd}              查询状态
  shutdown {cmd}             关闭守护进程
"""

import json
import logging
import os
import signal
import socket
import struct
import sys
import time
import traceback

# ── 项目路径 ──
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from lib.config import load_config
from lib.display.protocol import (
    DEFAULT_HOST, DEFAULT_PORT, MAX_PAYLOAD,
    MODE_FULL, MODE_PARTIAL,
)
from lib.display.renderer import create_layout
from lib.display.epaper_driver import EPaperDriver

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('display_server')


# ── Socket 帧协议 ──

def _send_frame(conn: socket.socket, data: dict):
    payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
    header = struct.pack('!I', len(payload))
    conn.sendall(header + payload)


def _recv_frame(conn: socket.socket) -> dict:
    header = conn.recv(4)
    if not header:
        raise ConnectionError("Connection closed")
    length = struct.unpack('!I', header)[0]
    if length > MAX_PAYLOAD:
        raise ValueError(f"Payload too large: {length} > {MAX_PAYLOAD}")
    payload = b''
    while len(payload) < length:
        chunk = conn.recv(length - len(payload))
        if not chunk:
            raise ConnectionError("Connection closed during read")
        payload += chunk
    return json.loads(payload.decode('utf-8'))


# ── 指令处理器 ──

class CommandHandler:
    """处理所有 Display Daemon 指令。"""

    def __init__(self, epd: EPaperDriver, layout):
        self._epd = epd
        self._layout = layout
        self._busy = False
        self._last_render = None
        self._last_mode = None
        self._last_full_time = None     # 上次重量级刷新时间
        self._last_partial_time = None  # 上次轻量级刷新时间
        self._epd_inited = False      # 是否已完成首次全刷 init

    @property
    def status(self) -> dict:
        return {
            "ok": True,
            "status": "busy" if self._busy else "idle",
            "last_render": self._last_render,
            "mode": self._last_mode,
        }

    def handle(self, request: dict) -> dict:
        cmd = request.get('cmd', '')
        logger.info("Command: %s", cmd)

        if cmd == 'status':
            return self.status

        if self._busy:
            return {"ok": False, "error": "display busy"}

        try:
            self._busy = True
            if cmd == 'render':
                return self._do_render(request)
            if cmd == 'clear':
                return self._do_clear()
            if cmd == 'sleep':
                return self._do_sleep()
            if cmd == 'shutdown':
                return self._do_shutdown()
            return {"ok": False, "error": f"unknown cmd: {cmd}"}
        finally:
            self._busy = False

    def _do_render(self, request: dict) -> dict:
        mode = request.get('mode', MODE_FULL)
        data = request.get('data', {})

        if not data:
            return {"ok": False, "error": "empty data"}

        # 记录刷新时间
        now_str = time.strftime('%Y-%m-%d %H:%M:%S')
        if mode == MODE_FULL:
            self._last_full_time = now_str
        elif mode == MODE_PARTIAL:
            self._last_partial_time = now_str

        # 注入刷新时间到渲染数据（底部状态栏）
        full_str = self._last_full_time or '--'
        partial_str = self._last_partial_time or '--'
        data = dict(data)  # 浅拷贝，避免修改调用方
        data['refresh_info'] = {
            'text': f'[full] {full_str} / [partial] {partial_str}',
        }

        try:
            if mode == MODE_FULL:
                img = self._layout.render_full(data)
                self._epd.init()
                self._epd.display_base(img)
                # 不 sleep — 保持 SPI/GPIO 打开，后续局部刷可复用
                self._epd_inited = True

                widget_summary = ", ".join(
                    f"{k}:{len(v) if isinstance(v, (list, dict)) else 1}"
                    for k, v in data.items()
                )
                logger.info("Full render: %s", widget_summary)

            elif mode == MODE_PARTIAL:
                if not self._epd_inited:
                    self._epd.init()
                    self._epd_inited = True
                img = self._layout.render_partial(data)
                self._epd.display_partial(img)

                logger.info("Partial render: %s", ", ".join(data.keys()))

            else:
                return {"ok": False, "error": f"unknown mode: {mode}"}

            self._last_render = time.strftime('%Y-%m-%dT%H:%M:%S')
            self._last_mode = mode
            return {"ok": True}

        except Exception as e:
            logger.error("Render error: %s", traceback.format_exc())
            return {"ok": False, "error": str(e)}

    def _do_clear(self) -> dict:
        try:
            self._epd.clear()
            return {"ok": True}
        except Exception as e:
            logger.error("Clear error: %s", e)
            return {"ok": False, "error": str(e)}

    def _do_sleep(self) -> dict:
        try:
            self._epd.sleep()
            self._epd_inited = False
            return {"ok": True}
        except Exception as e:
            logger.error("Sleep error: %s", e)
            return {"ok": False, "error": str(e)}

    def _do_shutdown(self) -> dict:
        return {"ok": True, "shutdown": True}


# ── 信号处理 ──

def _signal_handler(sig, frame):
    signame = signal.Signals(sig).name
    logger.info("Signal %s received, clearing screen...", signame)
    raise KeyboardInterrupt()


def _clear_screen_on_exit(epd):
    try:
        epd.clear()
        logger.info("Screen cleared on shutdown")
    except Exception as e:
        logger.warning("Screen clear on exit failed: %s", e)


# ── 主函数 ──

def main():
    import argparse
    parser = argparse.ArgumentParser(description='HAB Display Server')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f'Listen port (default: {DEFAULT_PORT})')
    parser.add_argument('--host', default=DEFAULT_HOST,
                        help=f'Bind address (default: {DEFAULT_HOST})')
    parser.add_argument('--config', help='Config file path')
    parser.add_argument('--mock', action='store_true',
                        help='Use mock EPD driver (for testing on non-Pi)')
    args = parser.parse_args()

    # 加载配置
    cfg = load_config(args.config)
    disp_cfg = getattr(cfg, 'display', None)
    epaper_cfg = getattr(cfg, 'epaper', None)

    # 覆写 mock 标志
    if args.mock:
        import lib.display.epaper_driver as epd_mod
        epd_mod._epd4in26 = None
        epd_mod._import_error = ImportError("Mock forced by --mock")

    logger.info("=== HAB Display Server ===")

    # 初始化墨水屏
    epd = EPaperDriver(epaper_cfg)
    logger.info("EPD: %s (%dx%d)",
                epaper_cfg.model if epaper_cfg else '4in26',
                epd.width, epd.height)

    # 初始化渲染器（Layout + Widget）
    font_dir = os.path.join(_PROJECT_ROOT, 'fonts')
    layout = create_layout(font_dir, disp_cfg)
    logger.info("Layout: %d widgets registered", len(layout.widgets))

    handler = CommandHandler(epd, layout)

    # 注册退出信号
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    logger.info("Signal handlers registered (SIGTERM, SIGINT)")

    # 启动 socket
    addr = (args.host, args.port)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(addr)
    server.listen(5)
    server.settimeout(1.0)
    logger.info("Listening on %s:%d", args.host, args.port)

    # 首次启动：显示待机画面
    try:
        idle_img = layout.idle_image()
        epd.init()
        epd.display_base(idle_img)
        epd.sleep()
        logger.info("Idle screen displayed")
        handler._last_render = time.strftime('%Y-%m-%dT%H:%M:%S')
        handler._last_mode = 'idle'
    except Exception as e:
        logger.warning("Idle screen display failed (may not be Pi): %s", e)

    try:
        while True:
            try:
                conn, client_addr = server.accept()
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break

            conn.settimeout(30.0)
            try:
                request = _recv_frame(conn)
                response = handler.handle(request)

                if response.get("shutdown"):
                    _send_frame(conn, response)
                    conn.close()
                    logger.info("Shutdown requested, exiting...")
                    return

                _send_frame(conn, response)

            except (json.JSONDecodeError, struct.error, ValueError) as e:
                logger.warning("Invalid request from %s: %s", client_addr, e)
                try:
                    _send_frame(conn, {"ok": False, "error": f"invalid request: {e}"})
                except OSError:
                    pass
            except ConnectionError as e:
                logger.warning("Connection error from %s: %s", client_addr, e)
            except Exception as e:
                logger.error("Handler error: %s\n%s", e, traceback.format_exc())
                try:
                    _send_frame(conn, {"ok": False, "error": str(e)})
                except OSError:
                    pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        _clear_screen_on_exit(epd)
        server.close()
        logger.info("Display Server stopped")


if __name__ == '__main__':
    main()
