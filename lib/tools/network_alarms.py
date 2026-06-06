"""get_network_alarms 工具实现。

基于 UniFi alarm 数据，列出网络告警：WAN 切换、AP 掉线、异常重启等。
"""
import logging
from collections import Counter
from datetime import datetime
from typing import Any

from lib.clients.unifi_client import UniFiClient
from lib.tools.base import Tool

logger = logging.getLogger(__name__)

_ALARM_NAMES: dict[str, str] = {
    'EVT_GW_WANTransition': 'WAN 线路切换',
    'EVT_AP_Lost_Contact': 'AP 掉线',
    'EVT_GW_Lost_Contact': '网关失联',
    'EVT_SW_Lost_Contact': '交换机失联',
    'EVT_GW_RestartedUnknown': '网关异常重启',
    'EVT_SW_RestartedUnknown': '交换机异常重启',
    'EVT_AP_RestartedUnknown': 'AP 异常重启',
    'EVT_GW_WANOverheat': '网关过热',
}


class GetNetworkAlarmsTool(Tool):
    name = 'get_network_alarms'
    description = (
        '获取网络告警列表，包括：各类告警的累计总数和近期发生次数、'
        'WAN 切换事件的时间分布、近期告警详情。'
    )

    def __init__(self, unifi: UniFiClient):
        self._unifi = unifi
        self.parameters = {
            'type': 'object',
            'properties': {
                'hours_back': {
                    'type': 'number',
                    'description': '告警回溯小时数，默认 24',
                    'minimum': 1,
                    'maximum': 168,
                },
            },
            'required': [],
            'additionalProperties': False,
        }

    def execute(self, hours_back: float = 24) -> dict:
        try:
            raw = self._unifi.get_alarms()
        except Exception as e:
            logger.warning('get_network_alarms failed: %s', e)
            return {'error': f'告警数据获取失败: {e}'}

        now_ms = datetime.now().timestamp() * 1000
        cutoff_ms = now_ms - hours_back * 3600 * 1000

        recent = [a for a in raw if a.get('time', 0) > cutoff_ms]
        all_keys = Counter(a.get('key', '?') for a in raw)
        recent_keys = Counter(a.get('key', '?') for a in recent)

        # 告警类别统计（全部 + 近期）
        alarm_counts = {}
        for key in all_keys:
            name = _ALARM_NAMES.get(key, key)
            alarm_counts[name] = {
                'total': all_keys[key],
                'recent': recent_keys.get(key, 0),
            }

        # 最近告警详情
        recent_sorted = sorted(recent, key=lambda x: x.get('time', 0), reverse=True)
        recent_detail = []
        for a in recent_sorted[:10]:
            ts = a.get('time', 0)
            time_str = datetime.fromtimestamp(ts / 1000).strftime('%m-%d %H:%M') if ts else '?'
            recent_detail.append({
                'time': time_str,
                'type': _ALARM_NAMES.get(a.get('key', '?'), a.get('key', '?')),
                'message': (a.get('msg', '') or '')[:100],
                'subsystem': a.get('subsystem', '?'),
            })

        # WAN 切换时间分布（按小时统计）
        wan_hours = Counter()
        wan_total = all_keys.get('EVT_GW_WANTransition', 0)
        for a in raw:
            if a.get('key') == 'EVT_GW_WANTransition':
                ts = a.get('time', 0) / 1000
                if ts > 0:
                    wan_hours[datetime.fromtimestamp(ts).hour] += 1

        return {
            'period_hours': hours_back,
            'total_alarms': len(raw),
            'alarms_in_period': len(recent),
            'alarm_counts': alarm_counts,
            'recent_alarms': recent_detail,
            'wan_transition_total': wan_total,
            'wan_transition_by_hour': dict(sorted(wan_hours.items())),
            'note': 'WAN 每日定时重拨，6:00 和 18:00 前后的故障转移属 ISP PPPoE 正常会话刷新，非异常。',
        }
