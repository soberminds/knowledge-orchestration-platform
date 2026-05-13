"""Provider capability registry and request option adapters for LLM calls."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

ThinkingMode = Literal["quick", "deep"]
ThinkingStyle = Literal["none", "deepseek", "qwen"]


@dataclass(frozen=True)
class CanonicalCompletionOptions:
    """Provider-agnostic completion intent from product/UI semantics."""

    thinking_mode: ThinkingMode
    stream: bool
    native_web_search: bool
    temperature: float
    max_tokens: int


@dataclass(frozen=True)
class ModelCapability:
    """Capability snapshot for one model at runtime."""

    supports_native_web_search: bool = False
    thinking_style: ThinkingStyle = "none"
    supports_reasoning_effort: bool = False
    deep_reasoning_effort: str = "high"
    supports_thinking_budget: bool = False
    deep_thinking_budget: int | None = None


class CapabilityRegistry:
    """Resolve model capabilities using provider defaults and optional overrides."""

    _ALLOWED_OVERRIDE_KEYS = {
        "supports_native_web_search",
        "thinking_style",
        "supports_reasoning_effort",
        "deep_reasoning_effort",
        "supports_thinking_budget",
        "deep_thinking_budget",
    }

    def __init__(
        self,
        *,
        capability_overrides_json: str,
        qwen_deep_thinking_budget: int,
        deepseek_deep_reasoning_effort: str,
    ) -> None:
        self._provider_defaults: dict[str, ModelCapability] = {
            "deepseek": ModelCapability(
                supports_native_web_search=False,
                thinking_style="deepseek",
                supports_reasoning_effort=True,
                deep_reasoning_effort=deepseek_deep_reasoning_effort or "high",
                supports_thinking_budget=False,
                deep_thinking_budget=None,
            ),
            "qwen": ModelCapability(
                supports_native_web_search=True,
                thinking_style="qwen",
                supports_reasoning_effort=False,
                deep_reasoning_effort="high",
                supports_thinking_budget=True,
                deep_thinking_budget=max(1, qwen_deep_thinking_budget),
            ),
        }
        self._overrides = self._parse_overrides(capability_overrides_json)

    def resolve(self, *, provider: str, model_name: str) -> ModelCapability:
        provider_token = provider.strip().lower()
        model_token = model_name.strip().lower()
        base = self._provider_defaults.get(provider_token, ModelCapability())

        override = self._match_override(model_token)
        if not override:
            return base
        return self._merge_capability(base, override)

    def supports_native_web_search(self, *, provider: str, model_name: str) -> bool:
        capability = self.resolve(provider=provider, model_name=model_name)
        return capability.supports_native_web_search

    def _parse_overrides(self, raw: str) -> dict[str, dict[str, Any]]:
        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}

        overrides: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            normalized_key = key.strip().lower()
            if not normalized_key:
                continue

            partial: dict[str, Any] = {}
            for field_name, raw_value in value.items():
                if field_name not in self._ALLOWED_OVERRIDE_KEYS:
                    continue
                if field_name in {
                    "supports_native_web_search",
                    "supports_reasoning_effort",
                    "supports_thinking_budget",
                }:
                    partial[field_name] = bool(raw_value)
                    continue
                if field_name == "thinking_style":
                    token = str(raw_value).strip().lower()
                    if token in {"none", "deepseek", "qwen"}:
                        partial[field_name] = token
                    continue
                if field_name == "deep_reasoning_effort":
                    effort = str(raw_value).strip().lower()
                    if effort:
                        partial[field_name] = effort
                    continue
                if field_name == "deep_thinking_budget":
                    try:
                        budget = int(raw_value)
                    except Exception:
                        continue
                    if budget >= 1:
                        partial[field_name] = budget
                    continue
            if partial:
                overrides[normalized_key] = partial
        return overrides

    def _match_override(self, model_token: str) -> dict[str, Any] | None:
        if not model_token:
            return None

        exact = self._overrides.get(model_token)
        if exact:
            return exact

        best_key = ""
        best_override: dict[str, Any] | None = None
        for raw_key, override in self._overrides.items():
            wildcard = raw_key.endswith("*")
            key = raw_key[:-1] if wildcard else raw_key
            if not key:
                continue
            if model_token.startswith(key) and len(key) > len(best_key):
                best_key = key
                best_override = override
        return best_override

    def _merge_capability(self, base: ModelCapability, override: dict[str, Any]) -> ModelCapability:
        payload = asdict(base)
        payload.update(override)
        return ModelCapability(**payload)


class ProviderOptionsAdapter:
    """Build provider-specific request options from canonical intent."""

    def build(
        self,
        *,
        canonical: CanonicalCompletionOptions,
        capability: ModelCapability,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if canonical.thinking_mode == "deep":
            options["max_tokens"] = min(canonical.max_tokens * 2, 4096)
        else:
            options["temperature"] = canonical.temperature
            options["max_tokens"] = canonical.max_tokens
        if canonical.stream:
            options["stream_options"] = {"include_usage": True}
        return options


class DeepSeekOptionsAdapter(ProviderOptionsAdapter):
    """Map canonical options to DeepSeek thinking parameters."""

    def build(
        self,
        *,
        canonical: CanonicalCompletionOptions,
        capability: ModelCapability,
    ) -> dict[str, Any]:
        options = super().build(canonical=canonical, capability=capability)
        extra_body: dict[str, Any] = {}

        if canonical.thinking_mode == "deep":
            extra_body["thinking"] = {"type": "enabled"}
            if capability.supports_reasoning_effort and capability.deep_reasoning_effort:
                options["reasoning_effort"] = capability.deep_reasoning_effort
        else:
            extra_body["thinking"] = {"type": "disabled"}

        if canonical.native_web_search and capability.supports_native_web_search:
            extra_body["enable_search"] = True

        if extra_body:
            options["extra_body"] = extra_body
        return options


class QwenOptionsAdapter(ProviderOptionsAdapter):
    """Map canonical options to Qwen deep-thinking parameters."""

    def build(
        self,
        *,
        canonical: CanonicalCompletionOptions,
        capability: ModelCapability,
    ) -> dict[str, Any]:
        options = super().build(canonical=canonical, capability=capability)
        extra_body: dict[str, Any] = {}

        if canonical.thinking_mode == "deep":
            extra_body["enable_thinking"] = True
            if capability.supports_thinking_budget and capability.deep_thinking_budget:
                extra_body["thinking_budget"] = capability.deep_thinking_budget
        else:
            extra_body["enable_thinking"] = False

        if canonical.native_web_search and capability.supports_native_web_search:
            extra_body["enable_search"] = True

        if extra_body:
            options["extra_body"] = extra_body
        return options


def build_provider_options(
    *,
    provider: str,
    capability: ModelCapability,
    canonical: CanonicalCompletionOptions,
) -> dict[str, Any]:
    """Public helper to map canonical options into provider request options."""

    provider_token = provider.strip().lower()
    if capability.thinking_style == "deepseek" or provider_token == "deepseek":
        adapter: ProviderOptionsAdapter = DeepSeekOptionsAdapter()
    elif capability.thinking_style == "qwen" or provider_token == "qwen":
        adapter = QwenOptionsAdapter()
    else:
        adapter = ProviderOptionsAdapter()
    return adapter.build(canonical=canonical, capability=capability)

