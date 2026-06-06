"""get_device_inventory 工具实现。

基于 UniFi alluser 数据，盘点家庭设备：新设备检测、离线设备、设备类型分布。
"""
import logging
import time
from typing import Any

from lib.clients.unifi_client import UniFiClient
from lib.tools.base import Tool

logger = logging.getLogger(__name__)

class GetDeviceInventoryTool(Tool):
    name = 'get_device_inventory'
    description = (
        '获取家庭设备盘点信息，包括：设备总览（在线/离线/总数）、'
        '近期新设备（24h 内首次出现）、长期离线设备列表、'
        '设备类型分布（手机/电脑/IoT 等）。可用于发现陌生设备和安全审计。'
    )

    def __init__(self, unifi: UniFiClient):
        self._unifi = unifi
        self.parameters = {
            'type': 'object',
            'properties': {
                'filter': {
                    'type': 'string',
                    'enum': ['all', 'new', 'offline', 'online'],
                    'description': '过滤条件。all=全部, new=24h新设备, offline=当前离线, online=当前在线。默认 all。',
                },
            },
            'required': [],
            'additionalProperties': False,
        }

    def execute(self, filter: str = 'all') -> dict:
        try:
            users = self._unifi.get_all_users()
        except Exception as e:
            logger.warning('get_device_inventory alluser failed: %s', e)
            return {'error': f'设备列表获取失败: {e}'}

        now = time.time()
        day_ago = now - 86400

        # 分类统计
        online = [u for u in users if u.get('last_seen', 0) > now - 300]  # 5min 内有活动
        wired = [u for u in users if u.get('is_wired')]
        wireless = [u for u in users if not u.get('is_wired')]
        new_24h = [u for u in users if u.get('first_seen', 0) > day_ago]
        long_offline = [u for u in users if 0 < u.get('last_seen', 0) < now - 86400 * 7]  # 7天+ 不在线

        result = {
            'total_devices': len(users),
            'online_devices': len(online),
            'offline_devices': len(users) - len(online),
            'wired_devices': len(wired),
            'wireless_devices': len(wireless),
            'new_devices_24h': len(new_24h),
            'long_offline_7d': len(long_offline),
        }

        if filter in ('new', 'all') and new_24h:
            result['new_devices'] = [
                {
                    'hostname': u.get('hostname', '?') or '?',
                    'mac': u.get('mac', '?'),
                    'first_seen': time.strftime(
                        '%m-%d %H:%M',
                        time.localtime(u.get('first_seen', 0)),
                    ),
                    'oui': u.get('oui', ''),
                    'is_wired': u.get('is_wired', False),
                }
                for u in new_24h[:10]
            ]

        if filter in ('offline', 'all') and long_offline:
            result['long_offline'] = [
                {
                    'hostname': u.get('hostname', '?') or '?',
                    'mac': u.get('mac', '?'),
                    'last_seen': time.strftime(
                        '%m-%d %H:%M',
                        time.localtime(u.get('last_seen', 0)),
                    ) if u.get('last_seen') else '从未上线',
                    'is_wired': u.get('is_wired', False),
                }
                for u in sorted(
                    long_offline,
                    key=lambda x: x.get('last_seen', 0),
                )[:10]
            ]

        if filter in ('online', 'all') and online:
            result['online_top'] = [
                {
                    'hostname': u.get('hostname', '?') or '?',
                    'ip': u.get('last_ip', '?'),
                    'ap': u.get('last_uplink_name', '?'),
                    'band': u.get('last_radio', '?'),
                    'is_wired': u.get('is_wired', False),
                    'uptime_hours': round(
                        (now - u.get('first_seen', now)) / 3600, 1
                    ) if u.get('first_seen') else 0,
                }
                for u in sorted(
                    online,
                    key=lambda x: x.get('last_seen', 0),
                    reverse=True,
                )[:10]
            ]

        return result
