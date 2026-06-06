"""final_output 工具实现。

验证并提交仪表盘最终内容。调用此工具后本轮交互结束。
"""
import logging
from typing import Any

from lib.tools.base import Tool

logger = logging.getLogger(__name__)


class FinalOutputTool(Tool):
    name = 'final_output'
    description = '提交仪表盘最终内容。sensor_panel 为传感器列表，summary 为摘要字符串列表。'

    def __init__(self):
        self.parameters = {
            'type': 'object',
            'properties': {
                'sensor_panel': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'label': {
                                'type': 'string',
                                'description': '显示标签',
                            },
                            'value': {
                                'type': 'string',
                                'description': '显示值',
                            },
                            'trend': {
                                'type': 'string',
                                'enum': ['↑', '↓', '→'],
                                'description': '趋势方向',
                            },
                            'remark': {
                                'type': 'string',
                                'description': '备注，如"较舒适""较2h前+2°C"，不要用emoji',
                            },
                        },
                        'required': ['label', 'value'],
                    },
                    'description': '传感器面板',
                    'maxItems': 6,
                },
                'summary': {
                    'type': 'array',
                    'items': {
                        'type': 'string',
                        'maxLength': 50,
                    },
                    'description': '摘要列表',
                    'minItems': 3,
                    'maxItems': 3,
                },
            },
            'required': ['sensor_panel', 'summary'],
            'additionalProperties': False,
        }

    def execute(self, **kwargs) -> dict:
        """验证参数并原样返回（Orchestrator 会拦截 final_output 特殊处理）。"""
        sensor = kwargs.get('sensor_panel', [])
        summary = kwargs.get('summary', [])

        if not isinstance(sensor, list) or len(sensor) > 6:
            raise ValueError('sensor_panel must be a list with ≤6 items')
        if not isinstance(summary, list) or len(summary) != 3:
            raise ValueError(f'summary must have exactly 3 items, got {len(summary)}')
        for i, s in enumerate(summary):
            if not isinstance(s, str):
                raise ValueError(f'summary[{i}] must be a string, got {type(s).__name__}')
            if len(s) > 50:
                raise ValueError(f'summary[{i}] too long ({len(s)}>30): {s}')

        return kwargs
