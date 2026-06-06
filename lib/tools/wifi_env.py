"""get_wifi_environment 工具实现。

分析 WiFi 环境：自家 AP 配置 + 周围干扰 AP + 信道拥塞评估。
"""
import logging
from typing import Any

from lib.clients.unifi_client import UniFiClient
from lib.tools.base import Tool

logger = logging.getLogger(__name__)


class GetWifiEnvironmentTool(Tool):
    name = 'get_wifi_environment'
    description = (
        '获取 WiFi 环境分析，包括自家 AP 列表及信道配置、'
        '周围干扰 AP 列表及信号强度、信道拥塞评估。'
    )

    def __init__(self, unifi: UniFiClient):
        self._unifi = unifi
        self.parameters = {
            'type': 'object',
            'properties': {
                'band': {
                    'type': 'string',
                    'enum': ['2g', '5g', 'all'],
                    'description': '频段过滤。2g=2.4GHz, 5g=5GHz, all=全部。默认 all。',
                },
            },
            'required': [],
            'additionalProperties': False,
        }

    def execute(self, band: str = 'all') -> dict:
        # 自家 AP
        try:
            devices = self._unifi.get_devices()
        except Exception as e:
            logger.warning('get_wifi_environment devices failed: %s', e)
            devices = []

        own_aps = []
        for d in devices:
            if d.get('type', '').lower() not in ('uap', 'ap'):
                continue  # 只处理 AP
            name = d.get('name', d.get('model', '?'))
            ap_info = {'name': name}

            for radio in d.get('radio_table', []):
                radio_name = radio.get('name', 'na')
                if 'ng' in radio_name:
                    ap_info['channel_2g'] = radio.get('channel', 0)
                    ap_info['tx_power_2g'] = radio.get('tx_power', 0)
                elif 'na' in radio_name:
                    ap_info['channel_5g'] = radio.get('channel', 0)
                    ap_info['tx_power_5g'] = radio.get('tx_power', 0)
                    ap_info['channel_width'] = radio.get('channel_width', 80)

            own_aps.append(ap_info)

        # 干扰 AP
        rogue_aps = {'total': 0, 'by_channel': {}, 'strong_interferers': []}
        try:
            rogue_data = self._unifi.get_rogue_aps()
            rogue_filtered = rogue_data

            # 频段过滤
            if band == '2g':
                rogue_filtered = [r for r in rogue_data if r.get('radio') == 'ng']
            elif band == '5g':
                rogue_filtered = [r for r in rogue_data if r.get('radio') == 'na']

            by_channel: dict[str, int] = {}
            strong = []
            for r in rogue_filtered:
                ch = str(r.get('channel', 0))
                by_channel[ch] = by_channel.get(ch, 0) + 1

                signal = r.get('signal', 0)
                if signal > -80:  # > -80dBm 算强干扰
                    strong.append({
                        'essid': r.get('essid', 'hidden'),
                        'channel': int(ch),
                        'signal_dbm': signal,
                        'radio': r.get('radio', '?'),
                    })

            strong.sort(key=lambda x: x['signal_dbm'], reverse=True)
            rogue_aps = {
                'total': len(rogue_filtered),
                'by_channel': dict(sorted(by_channel.items(), key=lambda x: int(x[0]))),
                'strong_interferers': strong[:8],
            }
        except Exception as e:
            logger.warning('get_wifi_environment rogue APs failed: %s', e)

        return {
            'own_aps': own_aps,
            'rogue_aps': rogue_aps,
        }
