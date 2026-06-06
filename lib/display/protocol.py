"""Display Server 通信协议。

Socket 协议格式 (TCP localhost:5150):
  - 长度前缀 + JSON 负载
  - 发送: [4字节大端长度][JSON字节]
  - 接收: [4字节大端长度][JSON字节]
  - 兼容调试: 也支持 JSON + \\n（无限定，仅用于 nc 手动测试）
"""

import json
import socket
import struct
import logging

logger = logging.getLogger(__name__)

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 5150
MAX_PAYLOAD  = 65536          # 最大负载 64KB
CONNECT_TIMEOUT = 3.0         # 连接超时(秒)
RW_TIMEOUT      = 30.0        # 读写超时(秒)


# ── 指令常量 ──

CMD_RENDER  = 'render'
CMD_CLEAR   = 'clear'
CMD_SLEEP   = 'sleep'
CMD_STATUS  = 'status'
CMD_SHUTDOWN = 'shutdown'

# 刷新模式
MODE_FULL    = 'full'
MODE_PARTIAL = 'partial'

# ── 辅助函数 ──

def _send_frame(conn: socket.socket, data: dict):
    """发送长度前缀的 JSON 帧。"""
    payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
    header = struct.pack('!I', len(payload))
    conn.sendall(header + payload)


def _recv_frame(conn: socket.socket) -> dict:
    """接收长度前缀的 JSON 帧。"""
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


# ── DisplayClient ──

class DisplayClient:
    """与 Display Server 通信的客户端。"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self._addr = (host, port)

    def _call(self, request: dict) -> dict:
        """发送请求并接收响应。"""
        try:
            with socket.create_connection(
                self._addr, timeout=CONNECT_TIMEOUT
            ) as conn:
                conn.settimeout(RW_TIMEOUT)
                _send_frame(conn, request)
                return _recv_frame(conn)
        except (ConnectionRefusedError, ConnectionError, OSError) as e:
            logger.warning("Display server unreachable: %s", e)
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error("DisplayClient error: %s", e)
            return {"ok": False, "error": str(e)}

    def render(self, data: dict, mode: str = MODE_FULL) -> bool:
        """渲染并显示。

        Args:
            data: final_output JSON dict。
            mode: MODE_FULL 或 MODE_PARTIAL。

        Returns:
            True 表示成功。
        """
        resp = self._call({"cmd": CMD_RENDER, "mode": mode, "data": data})
        return resp.get("ok") is True

    def clear(self) -> bool:
        resp = self._call({"cmd": CMD_CLEAR})
        return resp.get("ok") is True

    def sleep(self) -> bool:
        resp = self._call({"cmd": CMD_SLEEP})
        return resp.get("ok") is True

    def status(self) -> dict:
        return self._call({"cmd": CMD_STATUS})

    def shutdown(self) -> bool:
        resp = self._call({"cmd": CMD_SHUTDOWN})
        return resp.get("ok") is True
