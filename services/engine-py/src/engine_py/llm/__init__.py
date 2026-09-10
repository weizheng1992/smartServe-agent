"""LLM 统一入口子包。"""

from .chat import get_chat_model, get_embedding_model, get_vision_model, warm_embedding_model_in_background
from .resilience import CircuitBreaker, CircuitBreakerOpenError, global_circuit_breaker
from .telemetry import (
    bind_llm_call_context,
    bind_llm_call_node,
    drain_llm_call_writes,
    take_thread_token_total,
)

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "bind_llm_call_context",
    "bind_llm_call_node",
    "drain_llm_call_writes",
    "get_chat_model",
    "get_embedding_model",
    "get_vision_model",
    "global_circuit_breaker",
    "take_thread_token_total",
    "warm_embedding_model_in_background",
]
