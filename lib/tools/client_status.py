"""get_client_status 工具实现。

返回 WiFi 客户端连接数据：默认输出流量 TOP5，可按 MAC 查询单个设备。
"""
import logging
from typing import Any

from lib.clients.unifi_client import UniFiClient
from lib.tools.base import Tool

logger = logging.getLogger(__name__)

_ap_name_cache: dict[str, str] = {}


def _build_ap_name_cache(unifi: UniFiClient):
    global _ap_name_cache
    if _ap_name_cache:
        return
    try:
        devices = unifi.get_devices()
        for d in devices:
            mac = d.get('mac', '').lower()
            name = d.get('name', d.get('model', mac))
            _ap_name_cache[mac] = name
    except Exception:
        pass


def _format_client(c: dict, ap_name: str) -> dict:
    radio = c.get('radio', '')
    return {
        'hostname': c.get('hostname', '') or c.get('name', '?'),
        'ip': c.get('ip', '?'),
        'mac': c.get('mac', ''),
        'signal_dbm': c.get('signal', None),
        'channel': c.get('channel', 0),
        'band': '5G' if 'na' in str(radio) else '2.4G' if 'ng' in str(radio) else str(radio),
        'ap': ap_name,
        'is_wired': c.get('is_wired', False),
        'uptime_seconds': c.get('uptime', 0),
        'tx_rate_kbps': c.get('tx_rate', 0),
        'rx_rate_kbps': c.get('rx_rate', 0),
        'tx_bytes': c.get('tx_bytes', 0),
        'rx_bytes': c.get('rx_bytes', 0),
    }


class GetClientStatusTool(Tool):
    name = 'get_client_status'
    description = (
        '获取 WiFi/有线客户端连接状态。默认返回流量最高的 5 个设备；'
        '传入 mac 参数则仅返回指定设备的详细信息。'
    )

    def __init__(self, unifi: UniFiClient):
        self._unifi = unifi
        self.parameters = {
            'type': 'object',
            'properties': {
                'mac': {
                    'type': 'string',
                    'description': '设备 MAC 地址（格式 xx:xx:xx:xx:xx:xx），指定则只返回该设备。不传则返回流量 TOP5。',
                },
            },
            'required': [],
            'additionalProperties': False,
        }

    def execute(self, mac: str | None = None) -> dict:
        try:
            clients = self._unifi.get_clients()
        except Exception as e:
            logger.warning('get_client_status failed: %s', e)
            return {'total': 0, 'error': str(e)}

        _build_ap_name_cache(self._unifi)

        if mac:
            # 按 MAC 查找单个设备
            target = mac.lower()
            for c in clients:
                if c.get('mac', '').lower() == target:
                    ap_mac = c.get('ap_mac', '').lower()
                    ap_name = _ap_name_cache.get(ap_mac, ap_mac[:8])
                    return {
                        'total': len(clients),
                        'client': _format_client(c, ap_name),
                    }
            return {'total': len(clients), 'error': f'未找到设备 {mac}'}

        # 默认：流量 TOP5
        ranked = sorted(
            clients,
            key=lambda c: c.get('rx_bytes', 0) + c.get('tx_bytes', 0),
            reverse=True,
        )
        top5 = []
        for c in ranked[:5]:
            ap_mac = c.get('ap_mac', '').lower()
            ap_name = _ap_name_cache.get(ap_mac, ap_mac[:8])
            top5.append(_format_client(c, ap_name))

        return {
            'total': len(clients),
            'top_clients': top5,
        }
