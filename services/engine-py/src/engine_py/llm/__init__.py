"""LLM 统一入口子包。"""

from .chat import get_chat_model, get_embedding_model

__all__ = ["get_chat_model", "get_embedding_model"]
