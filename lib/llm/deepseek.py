"""DeepSeek LLM Provider（OpenAI 兼容 SDK）。

DeepSeek API 完全兼容 OpenAI SDK，仅 base_url 不同。
"""
import logging
import os
import time
from typing import Any

from openai import OpenAI

from .provider import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


def _count_tokens_est(messages: list[dict]) -> int:
    """粗略估算消息的 token 数（中文字符 * 2 + 英文字符）。"""
    total = 0
    for m in messages:
        content = m.get('content', '') or ''
        if isinstance(content, str):
            for ch in content:
                total += 2 if ord(ch) > 127 else 1
        tc = m.get('tool_calls')
        if tc:
            for t in tc:
                func = t.get('function', {})
                total += len(func.get('name', ''))
                total += len(str(func.get('arguments', '')))
        if m.get('role') == 'tool':
            c = m.get('content', '') or ''
            total += len(str(c))
    return total


class DeepSeekProvider(LLMProvider):
    """DeepSeek LLM 提供者（OpenAI SDK 实现）。"""

    def __init__(
        self,
        model: str = 'deepseek-chat',
        base_url: str = 'https://api.deepseek.com',
        api_key_env: str = 'DEEPSEEK_API_KEY',
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ):
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError(
                f'Environment variable {api_key_env} is not set. '
                'Please set it to your DeepSeek API key.'
            )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._call_count = 0

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        response_format: dict | None = None,
        **kwargs,
    ) -> LLMResponse:
        """调用 DeepSeek Chat Completions API。

        Args:
            messages: OpenAI 格式消息列表。
            tools: OpenAI function calling 格式工具定义。
            response_format: JSON 输出模式，如 {'type': 'json_object'}。
                             注意：与 tools 互斥，仅在不传 tools 时生效。
        """
        self._call_count += 1
        call_id = f'LLM#{self._call_count}'

        params = {
            'model': kwargs.get('model', self._model),
            'messages': messages,
            'max_tokens': kwargs.get('max_tokens', self._max_tokens),
            'temperature': kwargs.get('temperature', self._temperature),
        }
        # deepseek-v4 系列默认启用 thinking mode
        # thinking mode 不支持 temperature/top_p/presence_penalty 参数，设置会被静默忽略

        if tools:
            params['tools'] = tools
        elif response_format:
            params['response_format'] = response_format

        # 估算输入 token
        estimated_input = _count_tokens_est(messages)
        tool_count = len(tools) if tools else 0

        logger.info(
            '%s >> messages=%d, tools=%d, ~%d tok, model=%s',
            call_id, len(messages), tool_count, estimated_input, params['model'],
        )

        t0 = time.monotonic()
        try:
            resp = self._client.chat.completions.create(**params)
        except Exception as e:
            logger.error('%s >> API call failed after %.1fs: %s',
                         call_id, time.monotonic() - t0, e)
            raise

        duration = time.monotonic() - t0

        choice = resp.choices[0]
        msg = choice.message

        # 解析响应
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    'id': tc.id,
                    'type': tc.type,
                    'function': {
                        'name': tc.function.name,
                        'arguments': tc.function.arguments,
                    },
                })

        # 构建完整 assistant message（保留 reasoning_content 等 DeepSeek 特有字段）
        asst_msg = {'role': 'assistant'}
        if msg.content:
            asst_msg['content'] = msg.content
        else:
            asst_msg['content'] = None
        if tool_calls:
            asst_msg['tool_calls'] = tool_calls
        # DeepSeek thinking mode 需要在多轮中回传 reasoning_content
        rc = getattr(msg, 'reasoning_content', None)
        if rc:
            asst_msg['reasoning_content'] = rc

        # 响应摘要日志
        if tool_calls:
            names = ', '.join(tc['function']['name'] for tc in tool_calls)
            logger.info('%s << %.1fs, %d tool(s): %s', call_id, duration, len(tool_calls), names)
        elif msg.content:
            preview = msg.content.strip()[:100].replace('\n', ' ')
            logger.info('%s << %.1fs, text (%d chars): %s',
                        call_id, duration, len(msg.content), preview)
        else:
            logger.info('%s << %.1fs, empty response', call_id, duration)

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            assistant_message=asst_msg,
            raw=resp,
        )
