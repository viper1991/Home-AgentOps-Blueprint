"""get_trend 工具实现。

获取单个实体的历史趋势分析。
"""
import logging
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from lib.clients.ha_client import HAClient
from lib.tools.base import Tool

logger = logging.getLogger(__name__)


class GetTrendTool(Tool):
    name = 'get_trend'
    description = (
        '获取单个实体的历史趋势分析，返回当前值、最小值、最大值、'
        '平均值、趋势方向(↑↓→)和变化量。'
        'entity_id 从 get_room_status 返回值中获取。'
    )

    def __init__(
        self,
        ha: HAClient,
        max_calls: int = 3,
        max_hours: int = 4,
    ):
        self._ha = ha
        self.max_calls = max_calls
        self._max_hours = max_hours
        self.parameters = {
            'type': 'object',
            'properties': {
                'entity_id': {
                    'type': 'string',
                    'description': '实体 ID，如 climate.ke_ting_kong_diao',
                },
                'hours_back': {
                    'type': 'number',
                    'description': f'回溯小时数，范围 0.5-{max_hours}',
                    'minimum': 0.5,
                    'maximum': float(max_hours),
                },
            },
            'required': ['entity_id', 'hours_back'],
            'additionalProperties': False,
        }

    def execute(self, entity_id: str, hours_back: float = 2.0) -> dict:
        hour = min(hours_back, float(self._max_hours))
        now = datetime.now()
        start = now - timedelta(hours=hour)

        data = self._ha.get_history(entity_id, start, now)
        if not data:
            return {
                'entity_id': entity_id,
                'error': f'No history data for {entity_id} in past {hour}h',
                'current': None,
                'trend': '→',
            }

        # 提取数值状态（排除非数值状态如 "off"、"unavailable"）
        samples = []
        for point in data:
            state_str = point.get('state', '')
            try:
                val = float(state_str)
            except (ValueError, TypeError):
                continue
            ts = point.get('last_changed', point.get('last_updated', ''))
            samples.append({'time': ts, 'value': val})

        if not samples:
            return {
                'entity_id': entity_id,
                'error': f'No numeric data for {entity_id} in past {hour}h',
                'current': None,
                'trend': '→',
            }

        values = [s['value'] for s in samples]
        current = values[-1]
        first = values[0]
        min_val = min(values)
        max_val = max(values)
        avg_val = round(mean(values), 1)
        delta = round(current - first, 1)

        # 趋势判断
        if abs(delta) < 0.5:
            trend = '→'
        elif delta > 0:
            trend = '↑'
        else:
            trend = '↓'

        return {
            'entity_id': entity_id,
            'current': current,
            'min': min_val,
            'max': max_val,
            'avg': avg_val,
            'trend': trend,
            'delta': delta,
            'samples': samples,
        }
