"""Base adapter and shared data classes for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class AgentResponse:
    content: str | None
    tool_calls: list[ToolCall] | None
    usage: TokenUsage
    raw: Any

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMAdapter(ABC):
    """Abstract base class for LLM provider adapters."""

    @abstractmethod
    def format_tools(self, tools: list[dict]) -> list[dict]:
        ...

    @abstractmethod
    def format_messages(self, messages: list[dict]) -> list[dict]:
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AgentResponse:
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[dict]:
        ...
