"""提示词加载器。

从 config/prompts.yaml 加载所有 LLM 交互用的提示词和消息模板。
支持 {{placeholder}} 格式的字符串替换。
"""
import logging
import os
import re
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 默认路径
_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config', 'prompts.yaml',
)


class Prompts:
    """提示词配置加载与访问。

    用法:
        prompts = Prompts.load()
        system = prompts.get('system_prompt')
        msg = prompts.format('messages.quota_exhausted', tool_name='get_trend')
    """

    def __init__(self, data: dict):
        self._data = data

    @classmethod
    def load(cls, path: str | None = None) -> 'Prompts':
        """从 YAML 文件加载提示词配置。"""
        path = path or _DEFAULT_PATH
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        logger.info('Prompts loaded from %s', path)
        return cls(data)

    def get(self, key: str, default: Any = None) -> Any:
        """按点号路径获取值，如 'system_prompt' 或 'messages.discarded_tool_call'。"""
        parts = key.split('.')
        cur = self._data
        for p in parts:
            if isinstance(cur, dict):
                cur = cur.get(p)
                if cur is None:
                    return default
            else:
                return default
        return cur

    def format(self, key: str, **kwargs) -> str:
        """获取模板并用 kwargs 替换 {{placeholder}}。"""
        template = self.get(key, '')
        if not template:
            return template

        def _replace(match: re.Match) -> str:
            name = match.group(1).strip()
            return str(kwargs.get(name, match.group(0)))

        return re.sub(r'\{\{(\w+)\}\}', _replace, template)

    @property
    def system_prompt(self) -> str:
        """系统提示词。"""
        return self.get('system_prompt', '')

    def get_message(self, name: str, **kwargs) -> str:
        """获取 messages 下的提示词并格式化。"""
        return self.format(f'messages.{name}', **kwargs)
