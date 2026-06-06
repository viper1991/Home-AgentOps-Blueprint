"""工具调用计数器。

每次 LLM 调用某个工具时计数 +1，持久化到 JSON 文件。
文件路径为 config/tool_usage.json，内容为 {tool_name: count}。
"""
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

COUNTER_PATH = 'config/tool_usage.json'


def _load() -> dict:
    """加载计数器文件。"""
    try:
        if os.path.exists(COUNTER_PATH):
            with open(COUNTER_PATH, encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning('Failed to load tool counter: %s', e)
    return {}


def _save(data: dict):
    """保存计数器文件。"""
    try:
        with open(COUNTER_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.warning('Failed to save tool counter: %s', e)


def increment(tool_name: str, count: int = 1):
    """增加指定工具的调用计数。"""
    data = _load()
    old = data.get(tool_name, 0)
    data[tool_name] = data.get(tool_name, 0) + count
    _save(data)
    logger.debug('Tool counter: %s: %d -> %d', tool_name, old, data[tool_name])


def get_counts() -> dict:
    """获取所有工具计数。"""
    return _load()


def reset():
    """重置所有计数。"""
    _save({})
    logger.info('Tool counter reset')
