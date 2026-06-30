"""Normalized streaming event helpers for chat model output."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


StreamingEventType = Literal[
    "content_delta",
    "reasoning_delta",
    "tool_call_delta",
    "usage",
    "diagnostics",
    "done",
    "error",
]


class StreamingEvent(TypedDict, total=False):
    """Provider-neutral streaming event.

    The API layer can map these events to the current SSE contract while the
    backend gradually gains richer reasoning/tool/usage events.
    """

    type: StreamingEventType
    content_delta: str
    reasoning_delta: str
    tool_call_delta: dict[str, Any]
    usage: Any
    diagnostics: dict[str, Any]
    error: str
    answer: str
    rewritten_question: str
    hits: list[Any]
    citations: list[dict[str, Any]]
    model: str
    cost_estimate: Any
    model_diagnostics: dict[str, Any]


def content_delta(text: str) -> StreamingEvent:
    """Build a final-answer content delta event."""

    return {"type": "content_delta", "content_delta": text}


def reasoning_delta(text: str) -> StreamingEvent:
    """Build a provider reasoning delta event."""

    return {"type": "reasoning_delta", "reasoning_delta": text}


def tool_call_delta(payload: dict[str, Any]) -> StreamingEvent:
    """Build a provider tool-call delta event."""

    return {"type": "tool_call_delta", "tool_call_delta": payload}


def usage_event(usage: Any) -> StreamingEvent:
    """Build a token usage event."""

    return {"type": "usage", "usage": usage}


def diagnostics_event(diagnostics: dict[str, Any]) -> StreamingEvent:
    """Build a model diagnostics event."""

    return {"type": "diagnostics", "diagnostics": diagnostics}


def done_event(**payload: Any) -> StreamingEvent:
    """Build the terminal chat stream event."""

    return {"type": "done", **payload}


def error_event(message: str) -> StreamingEvent:
    """Build a stream error event."""

    return {"type": "error", "error": message}

