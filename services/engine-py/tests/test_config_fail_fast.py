"""LLM 配置 fail-fast 契约(persona-hardening 09,2026-09-30)。

钉死 `config.ensure_llm_config` 的四条行为边界 —— 均走子进程:`settings` 是
模块级单例且 LLM 工厂 lru_cache,进程内改 env 无法复现「env 没进进程」的
真实形状(2026-09 实弹前科:漏 --env-file 静默回退死端口 11211)。

1. import engine_py.config 在缺 AI_* 时必须容忍 —— alembic(db:push)/db:seed
   等不涉 LLM 的脚本不得被牵连拒启;
2. LLM 首用(get_chat_model)缺 AI_BASE_URL/AI_MODEL → 点名 ConfigError,
   报错须含变量名与 --env-file 指引;
3. 两项齐备 → 构造成功(不拨网络);
4. AI_API_KEY=dummy → 显式告警但不拒启(本地 mock 端点合法)。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import engine_py

_ENGINE_SRC = str(Path(engine_py.__file__).resolve().parents[1])

# 子进程最小可导入环境:DB/Redis 缺省本就 tolerant(config 只在连接期才失败)
_BASE_ENV = {
    "PATH": os.environ.get("PATH", ""),
    "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows 下 pathlib 需要
}


def _run(code: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {**_BASE_ENV, **(extra_env or {})}
    env["PYTHONPATH"] = _ENGINE_SRC + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,  # 返回码本身即断言素材,由各用例自行判定
    )


def test_import_config_tolerates_missing_llm_env() -> None:
    """缺 AI_* 时 import 必须成功:alembic / db:seed 不涉 LLM,不得被牵连拒启。"""
    proc = _run("import engine_py.config; print('IMPORT_OK')")
    assert proc.returncode == 0, f"import 竟被缺省 AI_* 拒绝:\n{proc.stderr}"
    assert "IMPORT_OK" in proc.stdout


def test_get_chat_model_missing_env_raises_named_config_error() -> None:
    """LLM 首用缺 AI_BASE_URL/AI_MODEL → 点名报错 + --env-file 指引,拒绝静默。"""
    proc = _run("from engine_py.llm.chat import get_chat_model; get_chat_model()")
    assert proc.returncode != 0, "缺 AI_BASE_URL/AI_MODEL 竟构造成功 —— fail-fast 失效"
    combined = proc.stderr + proc.stdout
    assert "AI_BASE_URL" in combined or "AI_MODEL" in combined, combined
    assert "--env-file" in combined, f"报错须给 --env-file 指引:\n{combined}"


def test_get_chat_model_with_env_constructs_without_network() -> None:
    """两项齐备(标记值即可)→ 构造成功;ChatOpenAI 构造期不拨网络。"""
    proc = _run(
        "from engine_py.llm.chat import get_chat_model;"
        "m = get_chat_model();"
        "assert m.model_name == 'unavailable-in-tests';"
        "print('CONSTRUCT_OK')",
        extra_env={"AI_BASE_URL": "http://127.0.0.1:1/unavailable", "AI_MODEL": "unavailable-in-tests"},
    )
    assert proc.returncode == 0, f"配置齐备竟拒启:\n{proc.stderr}"
    assert "CONSTRUCT_OK" in proc.stdout


def test_dummy_api_key_warns_but_does_not_reject() -> None:
    """AI_API_KEY=dummy → 告警打印但放行(本地 mock 端点合法;真实端点 401 近因可辨)。"""
    proc = _run(
        "from engine_py.llm.chat import get_chat_model;"
        "get_chat_model();"
        "print('CONSTRUCT_OK')",
        extra_env={
            "AI_BASE_URL": "http://127.0.0.1:1/unavailable",
            "AI_MODEL": "unavailable-in-tests",
            "AI_API_KEY": "dummy",
        },
    )
    assert proc.returncode == 0, f"dummy key 竟拒启(应为告警不拒启):\n{proc.stderr}"
    assert "AI_API_KEY" in proc.stdout and "dummy" in proc.stdout, proc.stdout
