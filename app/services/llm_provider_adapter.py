"""Formal LLM provider adapter layer."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.services.llm_provider_mapping import (
    CanonicalCompletionOptions,
    ModelCapability,
    build_provider_options,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderRuntimeConfig:
    """Runtime connection config for one provider."""

    provider: str
    base_url: str
    api_key: str


class ModelUnavailableError(RuntimeError):
    """Raised when selected model has no available provider credentials."""


class LLMProviderAdapter(ABC):
    """Provider-specific completion adapter boundary."""

    def __init__(
        self,
        *,
        config: ProviderRuntimeConfig,
        capability: ModelCapability,
        temperature: float,
        max_tokens: int,
    ) -> None:
        self.config = config
        self.capability = capability
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def provider(self) -> str:
        return self.config.provider

    @abstractmethod
    def create_chat_completion(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        thinking_mode: str,
        stream: bool,
        native_web_search: bool = False,
        diagnostics: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ):
        """Create a chat completion using provider-specific translation."""


class OpenAICompatibleProviderAdapter(LLMProviderAdapter):
    """Adapter for providers exposing OpenAI-compatible chat completions."""

    def __init__(
        self,
        *,
        config: ProviderRuntimeConfig,
        capability: ModelCapability,
        temperature: float,
        max_tokens: int,
        client: OpenAI,
    ) -> None:
        super().__init__(
            config=config,
            capability=capability,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._client = client

    def _completion_options(
        self,
        *,
        thinking_mode: str,
        stream: bool,
        native_web_search: bool,
    ) -> dict[str, Any]:
        canonical = CanonicalCompletionOptions(
            thinking_mode="deep" if thinking_mode == "deep" else "quick",
            stream=stream,
            native_web_search=native_web_search,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return build_provider_options(
            provider=self.provider,
            capability=self.capability,
            canonical=canonical,
        )

    @staticmethod
    def _append_diagnostic_warning(diagnostics: dict[str, Any] | None, message: str) -> None:
        if diagnostics is None:
            return
        warnings = diagnostics.setdefault("warnings", [])
        if isinstance(warnings, list) and message not in warnings:
            warnings.append(message)

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content or "")

        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type == "text":
                text_value = str(item.get("text") or "").strip()
                if text_value:
                    parts.append(text_value)
                continue
            if item_type == "image_url":
                image_payload = item.get("image_url")
                image_url = image_payload.get("url") if isinstance(image_payload, dict) else image_payload
                if image_url:
                    parts.append(f"[image_url] {image_url}")
        return "\n".join(parts)

    @classmethod
    def _messages_to_text_only(cls, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for message in messages:
            item = dict(message)
            item["content"] = cls._message_content_to_text(item.get("content", ""))
            normalized.append(item)
        return normalized

    def create_chat_completion(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        thinking_mode: str,
        stream: bool,
        native_web_search: bool = False,
        diagnostics: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ):
        options = self._completion_options(
            thinking_mode=thinking_mode,
            stream=stream,
            native_web_search=native_web_search,
        )
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": stream,
            **options,
        }
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        try:
            return self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            warning = (
                "模型扩展参数调用失败，后端已使用同一 provider/model 去掉扩展参数重试；"
                "本次回答的原生联网或深度思考可能没有生效。"
            )
            logger.warning(
                "LLM extended-options call failed; retrying without extra options. "
                "provider=%s model=%s stream=%s option_keys=%s error=%s",
                self.provider,
                model_name,
                stream,
                sorted(options.keys()),
                exc,
            )
            if diagnostics is not None:
                diagnostics["option_fallback_used"] = True
            self._append_diagnostic_warning(diagnostics, warning)
            fallback_kwargs: dict[str, Any] = {
                "model": model_name,
                "messages": self._messages_to_text_only(messages),
                "stream": stream,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            return self._client.chat.completions.create(**fallback_kwargs)


class QwenResponsesProviderAdapter(OpenAICompatibleProviderAdapter):
    """Adapter for Qwen models that should use OpenAI-compatible Responses API."""

    @staticmethod
    def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _messages_to_responses_input(self, messages: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = self._message_content_to_text(message.get("content", ""))
            if content.strip():
                lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if output_text:
            return str(output_text)

        output = getattr(response, "output", None)
        if not isinstance(output, list):
            return ""
        parts: list[str] = []
        for item in output:
            content = getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for part in content:
                text_value = getattr(part, "text", None)
                if text_value:
                    parts.append(str(text_value))
        return "".join(parts)

    @staticmethod
    def _responses_usage_to_chat_usage(response: Any) -> dict[str, int] | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0) or input_tokens + output_tokens
        return {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _chat_completion_shape(
        *,
        model_name: str,
        text: str,
        usage: dict[str, int] | None,
    ) -> Any:
        class _Message:
            content = text
            tool_calls = []

            @staticmethod
            def model_dump(*, exclude_none: bool = False) -> dict[str, Any]:
                return {"role": "assistant", "content": text}

        class _Choice:
            message = _Message()

        class _Completion:
            model = model_name
            choices = [_Choice()]
            usage = usage

        return _Completion()

    @classmethod
    def _response_stream_delta_text(cls, event: Any) -> str:
        event_type = str(cls._obj_get(event, "type", cls._obj_get(event, "event", "")) or "")
        if event_type and event_type not in {
            "response.output_text.delta",
            "response.text.delta",
            "response.reasoning_text.delta",
            "response.reasoning.delta",
            "output_text.delta",
            "text.delta",
        }:
            return ""

        for key in ("delta", "text", "content"):
            value = cls._obj_get(event, key)
            if isinstance(value, str) and value:
                return value

        item = cls._obj_get(event, "item")
        if item is not None:
            for key in ("delta", "text", "content"):
                value = cls._obj_get(item, key)
                if isinstance(value, str) and value:
                    return value
        return ""

    @classmethod
    def _response_stream_reasoning_text(cls, event: Any) -> str:
        event_type = str(cls._obj_get(event, "type", cls._obj_get(event, "event", "")) or "")
        if "reasoning" not in event_type:
            return ""
        for key in ("delta", "text", "content"):
            value = cls._obj_get(event, key)
            if isinstance(value, str) and value:
                return value
        return ""

    @classmethod
    def _response_stream_completed_response(cls, event: Any) -> Any | None:
        event_type = str(cls._obj_get(event, "type", cls._obj_get(event, "event", "")) or "")
        if event_type not in {"response.completed", "response.done", "completed", "done"}:
            return None
        return cls._obj_get(event, "response", event)

    @staticmethod
    def _chat_stream_chunk_shape(
        *,
        model_name: str,
        content: str = "",
        reasoning_content: str = "",
    ) -> Any:
        class _Delta:
            def __init__(self) -> None:
                self.content = content
                self.reasoning_content = reasoning_content
                self.tool_calls: list[Any] = []

        class _Choice:
            def __init__(self) -> None:
                self.delta = _Delta()

        class _Chunk:
            def __init__(self) -> None:
                self.model = model_name
                self.choices = [_Choice()]

        return _Chunk()

    def _responses_stream_to_chat_stream(self, response_stream: Any, model_name: str):
        saw_text_delta = False
        completed_response: Any | None = None
        for event in response_stream:
            completed = self._response_stream_completed_response(event)
            if completed is not None:
                completed_response = completed
                continue

            reasoning_text = self._response_stream_reasoning_text(event)
            if reasoning_text:
                yield self._chat_stream_chunk_shape(
                    model_name=model_name,
                    reasoning_content=reasoning_text,
                )
                continue

            text_delta = self._response_stream_delta_text(event)
            if not text_delta:
                continue
            saw_text_delta = True
            yield self._chat_stream_chunk_shape(model_name=model_name, content=text_delta)

        if not saw_text_delta and completed_response is not None:
            final_text = self._extract_response_text(completed_response)
            if final_text:
                yield self._chat_stream_chunk_shape(model_name=model_name, content=final_text)

    def create_chat_completion(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        thinking_mode: str,
        stream: bool,
        native_web_search: bool = False,
        diagnostics: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ):
        if (
            tools
            or not native_web_search
            or not self.capability.supports_responses_api
            or (stream and not self.capability.supports_responses_streaming)
        ):
            if native_web_search and diagnostics is not None and not self.capability.supports_responses_api:
                self._append_diagnostic_warning(
                    diagnostics,
                    "当前模型未声明支持千问 Responses API，已使用 Chat Completions 兼容接口。",
                )
            if native_web_search and stream and diagnostics is not None and not self.capability.supports_responses_streaming:
                self._append_diagnostic_warning(
                    diagnostics,
                    "当前模型未声明支持 Responses API 流式，已使用 Chat Completions 流式接口。",
                )
            return super().create_chat_completion(
                model_name=model_name,
                messages=messages,
                thinking_mode=thinking_mode,
                stream=stream,
                native_web_search=native_web_search,
                diagnostics=diagnostics,
                tools=tools,
                tool_choice=tool_choice,
            )

        try:
            response_kwargs: dict[str, Any] = {
                "model": model_name,
                "input": self._messages_to_responses_input(messages),
                "tools": [{"type": "web_search"}],
            }
            if stream:
                response_kwargs["stream"] = True
            response = self._client.responses.create(**response_kwargs)
            if diagnostics is not None:
                diagnostics["provider_api"] = "qwen_responses_stream" if stream else "qwen_responses"
            if stream:
                return self._responses_stream_to_chat_stream(response, model_name=model_name)
            return self._chat_completion_shape(
                model_name=str(getattr(response, "model", "") or model_name),
                text=self._extract_response_text(response),
                usage=self._responses_usage_to_chat_usage(response),
            )
        except Exception as exc:
            self._append_diagnostic_warning(
                diagnostics,
                f"千问 Responses API 调用失败，已退回 Chat Completions：{exc}",
            )
            if diagnostics is not None:
                diagnostics["provider_api"] = "chat_completions_fallback"
            return super().create_chat_completion(
                model_name=model_name,
                messages=messages,
                thinking_mode=thinking_mode,
                stream=stream,
                native_web_search=native_web_search,
                diagnostics=diagnostics,
                tools=tools,
                tool_choice=tool_choice,
            )


class LLMProviderAdapterFactory:
    """Create and cache provider adapters."""

    def __init__(self, *, qwen_responses_api_enabled: bool = False) -> None:
        self._openai_clients: dict[str, OpenAI] = {}
        self._qwen_responses_api_enabled = bool(qwen_responses_api_enabled)

    def create(
        self,
        *,
        config: ProviderRuntimeConfig,
        capability: ModelCapability,
        temperature: float,
        max_tokens: int,
    ) -> LLMProviderAdapter:
        if not config.api_key:
            env_name = f"{config.provider.upper()}_API_KEY"
            raise ModelUnavailableError(
                f"Model provider '{config.provider}' is temporarily unavailable: missing {env_name}. "
                "Please set it in .env, then restart backend."
            )
        if not config.base_url:
            env_name = f"{config.provider.upper()}_BASE_URL"
            raise ModelUnavailableError(
                f"Model provider '{config.provider}' is temporarily unavailable: missing {env_name}. "
                "Please set it in .env, then restart backend."
            )

        cache_key = f"{config.provider}|{config.base_url}|{hash(config.api_key)}"
        client = self._openai_clients.get(cache_key)
        if client is None:
            client = OpenAI(api_key=config.api_key, base_url=config.base_url)
            self._openai_clients[cache_key] = client

        if config.provider.strip().lower() == "qwen" and self._qwen_responses_api_enabled:
            return QwenResponsesProviderAdapter(
                config=config,
                capability=capability,
                temperature=temperature,
                max_tokens=max_tokens,
                client=client,
            )

        return OpenAICompatibleProviderAdapter(
            config=config,
            capability=capability,
            temperature=temperature,
            max_tokens=max_tokens,
            client=client,
        )
