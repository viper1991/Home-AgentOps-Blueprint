"""get_traffic_analysis 工具实现。

基于 UniFi DPI 数据，分析全站流量：TOP 应用排行、分类分布、异常流量。
"""
import logging
from typing import Any

from lib.clients.unifi_client import UniFiClient
from lib.dpi_apps import get_app_name, get_cat_name
from lib.tools.base import Tool

logger = logging.getLogger(__name__)


class GetTrafficAnalysisTool(Tool):
    name = 'get_traffic_analysis'
    description = (
        '获取家庭网络流量分析，包括：TOP 应用流量排行（按下载/上传）、'
        '流量分类分布（视频/社交/游戏等占比）、异常大流量应用检测。'
        '可指定查看全站整体或单个设备的流量画像。'
    )

    def __init__(self, unifi: UniFiClient):
        self._unifi = unifi
        self.parameters = {
            'type': 'object',
            'properties': {
                'scope': {
                    'type': 'string',
                    'enum': ['site', 'device'],
                    'description': '分析范围。site=全站总览, device=单设备详情。默认 site。',
                },
                'mac': {
                    'type': 'string',
                    'description': '设备 MAC 地址（scope=device 时必填，格式 xx:xx:xx:xx:xx:xx）',
                },
            },
            'required': [],
            'additionalProperties': False,
        }

    def execute(self, scope: str = 'site', mac: str | None = None) -> dict:
        if scope == 'device' and not mac:
            return {'error': 'scope=device 时必须提供 mac 参数'}

        if scope == 'device':
            return self._device_dpi(mac)
        return self._site_dpi()

    def _site_dpi(self) -> dict:
        """全站 DPI 分析。"""
        try:
            raw = self._unifi.get_dpi_by_app()
        except Exception as e:
            logger.warning('get_traffic_analysis sitedpi failed: %s', e)
            return {'error': f'DPI 数据获取失败: {e}'}

        if not raw:
            return {'top_apps': [], 'categories': [], 'total_gb': 0}

        apps = raw[0].get('by_app', [])

        # 按总流量排序
        ranked = sorted(
            apps,
            key=lambda x: x.get('rx_bytes', 0) + x.get('tx_bytes', 0),
            reverse=True,
        )

        total_bytes = sum(a.get('rx_bytes', 0) + a.get('tx_bytes', 0) for a in ranked)
        total_gb = round(total_bytes / (1024 ** 3), 1)

        # TOP 15 应用
        top_apps = []
        for a in ranked[:15]:
            app_id = a.get('app', 0)
            rx_mb = round(a.get('rx_bytes', 0) / (1024 ** 2), 1)
            tx_mb = round(a.get('tx_bytes', 0) / (1024 ** 2), 1)
            share = round((rx_mb + tx_mb) / (total_gb * 1024) * 100, 1) if total_gb > 0 else 0
            top_apps.append({
                'app': get_app_name(app_id),
                'download_mb': rx_mb,
                'upload_mb': tx_mb,
                'traffic_share_pct': share,
                'clients': a.get('known_clients', 0),
            })

        # 分类汇总
        cats_raw: dict[int, dict] = {}
        for a in ranked:
            cid = a.get('cat', 0)
            if cid not in cats_raw:
                cats_raw[cid] = {'rx': 0, 'tx': 0, 'apps': set()}
            cats_raw[cid]['rx'] += a.get('rx_bytes', 0)
            cats_raw[cid]['tx'] += a.get('tx_bytes', 0)
            cats_raw[cid]['apps'].add(a.get('app', 0))

        categories = []
        for cid, data in sorted(cats_raw.items(),
                                 key=lambda x: x[1]['rx'] + x[1]['tx'],
                                 reverse=True):
            total_mb = round((data['rx'] + data['tx']) / (1024 ** 2), 1)
            share = round(total_mb / (total_gb * 1024) * 100, 1) if total_gb > 0 else 0
            categories.append({
                'category': get_cat_name(cid),
                'total_mb': total_mb,
                'traffic_share_pct': share,
                'app_count': len(data['apps']),
            })

        return {
            'top_apps': top_apps,
            'categories': categories[:10],
            'total_traffic_gb': total_gb,
        }

    def _device_dpi(self, mac: str) -> dict:
        """单设备 DPI 画像。"""
        data = self._unifi.post(
            f'/api/s/{self._unifi.site}/stat/stadpi',
            json={'type': 'by_app', 'macs': [mac]},
            timeout=30,
        )
        if not data:
            return {'error': '设备 DPI 获取失败（UniFi 不可用或返回空数据）'}

        apps = data[0].get('by_app', [])
        ranked = sorted(
            apps,
            key=lambda x: x.get('rx_bytes', 0) + x.get('tx_bytes', 0),
            reverse=True,
        )

        total_kb = sum(a.get('rx_bytes', 0) + a.get('tx_bytes', 0) for a in ranked) / 1024

        top = []
        for a in ranked[:10]:
            app_id = a.get('app', 0)
            rx_kb = round(a.get('rx_bytes', 0) / 1024, 1)
            tx_kb = round(a.get('tx_bytes', 0) / 1024, 1)
            top.append({
                'app': get_app_name(app_id),
                'download_kb': rx_kb,
                'upload_kb': tx_kb,
            })

        return {
            'device_mac': mac,
            'total_traffic_kb': round(total_kb, 1),
            'top_apps': top,
        }
