"""LLM 交互日志记录器。

每次 LLM 调用的完整输入/输出写入 JSONL 文件（logs/interactions/），
同时支持在 console logger 输出结构化摘要。
"""
import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# 日志目录
LOG_DIR = 'logs/interactions'

# 输入摘要的消息体截断长度
_CONTENT_PREVIEW_LEN = 150


def _summarize_messages(messages: list[dict]) -> dict:
    """生成 messages 的结构化摘要（用于 console 日志）。"""
    summary = {
        'total': len(messages),
        'roles': {},
        'tool_calls': 0,
        'estimated_chars': 0,
    }

    for m in messages:
        role = m.get('role', '?')
        summary['roles'][role] = summary['roles'].get(role, 0) + 1

        tool_calls = m.get('tool_calls')
        if tool_calls:
            summary['tool_calls'] += len(tool_calls)

        # 估算字符数
        content = m.get('content', '')
        if isinstance(content, str):
            summary['estimated_chars'] += len(content)
        elif content is not None:
            summary['estimated_chars'] += len(str(content))

        # tool result content
        if role == 'tool':
            tc = m.get('content', '')
            if isinstance(tc, str):
                summary['estimated_chars'] += len(tc)

    return summary


def _summarize_response(response: Any) -> dict:
    """生成 LLM 响应的结构化摘要。"""
    summary = {
        'has_content': False,
        'tool_calls': 0,
        'tool_names': [],
    }

    if hasattr(response, 'content') and response.content:
        summary['has_content'] = True
        summary['content_preview'] = response.content[:_CONTENT_PREVIEW_LEN]

    if hasattr(response, 'tool_calls') and response.tool_calls:
        summary['tool_calls'] = len(response.tool_calls)
        summary['tool_names'] = [
            tc.get('function', {}).get('name', '?')
            for tc in response.tool_calls
        ]
        if response.tool_calls:
            first = response.tool_calls[0]
            args = first.get('function', {}).get('arguments', '') or ''
            summary['first_args_preview'] = str(args)[:_CONTENT_PREVIEW_LEN]

    return summary


class InteractionLog:
    """LLM 交互日志（JSONL 文件）。"""

    def __init__(self, run_label: str = 'heavyweight'):
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._path = os.path.join(LOG_DIR, f'{run_label}_{ts}.jsonl')
        logger.info('Interaction log: %s', self._path)

    def record(
        self,
        round_num: int,
        interaction_type: str,
        messages: list[dict],
        response: Any,
        duration_ms: int | None = None,
    ):
        """写入一条 LLM 交互记录。"""
        entry = {
            'timestamp': datetime.now().isoformat(timespec='milliseconds'),
            'round': round_num,
            'type': interaction_type,
            'messages': self._truncate_messages(messages),
            'response': self._format_response(response),
        }
        if duration_ms is not None:
            entry['duration_ms'] = duration_ms

        # 提取 token 使用量（OpenAI/DeepSeek API usage）
        raw = getattr(response, 'raw', None)
        if raw and hasattr(raw, 'usage') and raw.usage:
            entry['usage'] = {
                'prompt_tokens': getattr(raw.usage, 'prompt_tokens', 0),
                'completion_tokens': getattr(raw.usage, 'completion_tokens', 0),
                'total_tokens': getattr(raw.usage, 'total_tokens', 0),
            }

        # 提取 reasoning_content（DeepSeek thinking mode）
        reasoning = getattr(response, 'assistant_message', None)
        if reasoning and reasoning.get('reasoning_content'):
            entry['reasoning_content'] = reasoning['reasoning_content']

        # 工具调用摘要（便于快速查看每轮的工具使用）
        if hasattr(response, 'tool_calls') and response.tool_calls:
            tool_summary = []
            for tc in response.tool_calls:
                fn = tc.get('function', {})
                try:
                    args = json.loads(fn.get('arguments', '{}'))
                except (json.JSONDecodeError, TypeError):
                    args = fn.get('arguments', '')
                tool_summary.append({
                    'name': fn.get('name', ''),
                    'args': args,
                })
            entry['tool_calls_summary'] = tool_summary

        try:
            with open(self._path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except OSError as e:
            logger.warning('Failed to write interaction log: %s', e)

    # console logger 的输出由 DeepSeekProvider 或调用方完成
    @staticmethod
    def log_console(
        round_num: int,
        interaction_type: str,
        messages: list[dict],
        response: Any,
        duration_ms: int | None = None,
    ):
        """输出 LLM 交互摘要到 console logger。"""
        msg_summary = _summarize_messages(messages)
        resp_summary = _summarize_response(response)

        lines = [
            f'── LLM Round {round_num} [{interaction_type}] ──',
            f'  Input:  {msg_summary["total"]} msgs '
            f'({", ".join(f"{k}={v}" for k, v in msg_summary["roles"].items())}), '
            f'~{msg_summary["estimated_chars"]} chars',
        ]

        if duration_ms is not None:
            lines.append(f'  Time:   {duration_ms}ms')

        if resp_summary['tool_calls'] > 0:
            tools = ', '.join(resp_summary['tool_names'])
            lines.append(f'  Output: {resp_summary["tool_calls"]} tool call(s): {tools}')
        elif resp_summary['has_content']:
            preview = resp_summary.get('content_preview', '')[:120]
            lines.append(f'  Output: text ({len(preview)} chars)')
        else:
            lines.append('  Output: empty')

        logger.info('\n'.join(lines))

    # ── 序列化辅助 ──

    @staticmethod
    def _truncate_messages(messages: list[dict]) -> list[dict]:
        """返回完整的 messages 列表（不截断）。"""
        return list(messages)

    @staticmethod
    def _format_response(response: Any) -> dict:
        """将 LLMResponse 转为可序列化的 dict（不截断）。"""
        tc_list = []
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tc in response.tool_calls:
                func = tc.get('function', {})
                tc_list.append({
                    'id': tc.get('id', ''),
                    'type': tc.get('type', 'function'),
                    'function': {
                        'name': func.get('name', ''),
                        'arguments': func.get('arguments', ''),
                    },
                })

        # 提取 reasoning_content（DeepSeek thinking mode）
        asst = getattr(response, 'assistant_message', None) or {}
        reasoning = asst.get('reasoning_content', '') or ''

        return {
            'content': getattr(response, 'content', None),
            'tool_calls': tc_list,
            'reasoning_content': reasoning,
        }
