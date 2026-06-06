"""LLM Provider 抽象基类。

定义统一的 LLM 交互接口，兼容 OpenAI / DeepSeek / Anthropic 等 API。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """统一的 LLM 响应结构。"""
    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    # 完整的 assistant message dict（含 reasoning_content），用于多轮对话回传
    assistant_message: dict | None = None
    # 原始 API 响应（调试用）
    raw: Any = None


class LLMProvider(ABC):
    """LLM 提供者抽象基类。"""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """发送对话消息并获取响应。

        Args:
            messages: OpenAI 格式消息列表。
            tools: OpenAI function calling 格式工具定义列表。
            **kwargs: 额外参数（temperature, max_tokens 等）。

        Returns:
            LLMResponse，包含 content 和 tool_calls。
        """
        ...
