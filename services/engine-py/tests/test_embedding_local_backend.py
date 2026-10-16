"""本地 embedding 后端契约(2026-10-15 夜评台账 #1:fastembed/ONNX 替换 torch)。

钉三件事:
1. local 提供方走 fastembed 适配层(_FastembedEmbeddings),numpy 行向量
   正确转 list[float],与 _SerializedEmbeddings 串行护栏组合;
2. lru_cache 单例:换后端不改变「全进程一个实例」契约;
3. openai 提供方路径不受影响(网络客户端,不经适配层)。
真模型烟雾(维度/归一化/无 torch 导入)在 scripts 层手动执行,不进套件
(首用需经 HF 镜像拉 ONNX 权重,套件保持离线确定性)。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from engine_py.llm import chat as chat_module
from engine_py.llm.chat import get_embedding_model


class _StubFastembed:
    """fastembed.TextEmbedding 桩:embed 返回 numpy 矩阵(行=文本)。"""

    def __init__(self, model_name: str, **kwargs: Any) -> None:
        self.model_name = model_name
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[Any]:
        self.calls.append(list(texts))
        import numpy as np

        return [np.array([0.1 * (k + 1) for k in range(4)]) for _ in texts]


@pytest.fixture()
def local_backend(monkeypatch):
    monkeypatch.setattr(chat_module, "settings", replace(chat_module.settings, embedding_provider="local"))
    monkeypatch.setattr("fastembed.TextEmbedding", _StubFastembed)
    get_embedding_model.cache_clear()
    yield
    get_embedding_model.cache_clear()


def test_local_provider_uses_fastembed_adapter(local_backend):
    model = get_embedding_model()
    assert type(model).__name__ == "_SerializedEmbeddings", "串行护栏必须仍在(防御纵深)"
    inner = model._inner
    assert type(inner).__name__ == "_FastembedEmbeddings", "local 提供方必须走 fastembed 适配层"
    vec = asyncio.run(model.aembed_query("冲锋衣"))
    assert isinstance(vec, list) and all(isinstance(x, float) for x in vec)
    assert len(vec) == 4


def test_cache_dir_env_passthrough(monkeypatch, local_backend):
    """FASTEMBED_CACHE_PATH 透传给 TextEmbedding(2026-10-15 安全审计 #4):
    缺省 tempdir 会让容器每次启动重拉 ONNX 权重并进进程执行 —— 生产必须
    可配到部署卷;网关进程同时验证显式 env 生效。"""
    captured: dict = {}

    class _Capture(_StubFastembed):
        def __init__(self, model_name: str = "", **kwargs: Any) -> None:
            captured.update(kwargs)
            captured["model_name"] = model_name
            super().__init__(model_name)

    monkeypatch.setenv("FASTEMBED_CACHE_PATH", "/data/fastembed")
    monkeypatch.setattr("fastembed.TextEmbedding", _Capture)
    get_embedding_model.cache_clear()
    try:
        get_embedding_model()
    finally:
        get_embedding_model.cache_clear()
    assert captured.get("cache_dir") == "/data/fastembed", f"cache_dir 必须透传: {captured}"


def test_embedding_singleton_survives_backend_swap(local_backend):
    assert get_embedding_model() is get_embedding_model(), "lru_cache 单例契约不因换后端改变"


def test_openai_provider_path_untouched(monkeypatch):
    """openai 提供方不经 fastembed 适配层(网络客户端,线程安全)。"""
    monkeypatch.setattr(chat_module, "settings", replace(chat_module.settings, embedding_provider="openai"))
    monkeypatch.setattr(chat_module, "ensure_llm_config", lambda *_: None)
    get_embedding_model.cache_clear()
    try:
        model = get_embedding_model()
        assert type(model).__name__ == "OpenAIEmbeddings"
    finally:
        get_embedding_model.cache_clear()
