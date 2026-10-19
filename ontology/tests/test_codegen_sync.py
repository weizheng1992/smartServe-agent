"""codegen 漂移门(ADR-0015 批一)。

① 生成物文件内容必须与 registry.emit_python() 全文相等(声明改了没再生成 → 红);
② 生成物 import 后的常量与 registry 派生值相等(生成器语义漂移 → 红)。

engine/gateway 运行时只 import 生成物(engine_py.ontology_generated,自包含
零依赖);声明层 → 生成物 的唯一再生成入口:
`services/.venv/bin/python ontology/registry.py --write`
"""

from __future__ import annotations

from ontology import (
    CUSTOMER_ACTIONS,
    DEFAULT_REFUND_AUTO_APPROVAL_LIMIT,
    ENGINE_HANDLED_ACTIONS,
    GENERATED_PY_PATH,
    OPERATOR_ACTIONS,
    SPI_ACTIONS,
    STAFF_REVIEW_ACTIONS,
    TS_GHOST_ACTIONS,
    emit_python,
)


def test_generated_file_in_sync() -> None:
    assert GENERATED_PY_PATH.exists(), (
        f"生成物缺失:{GENERATED_PY_PATH};再生成 = services/.venv/bin/python ontology/registry.py --write"
    )
    on_disk = GENERATED_PY_PATH.read_text(encoding="utf-8")
    assert on_disk == emit_python(), (
        "ontology_generated.py 与声明层漂移 —— 改了 ontology/*.yaml 须执行 "
        "`services/.venv/bin/python ontology/registry.py --write` 再提交"
    )


def test_generated_module_constants_match_registry() -> None:
    from engine_py import ontology_generated as gen

    assert gen.CUSTOMER_ACTIONS == CUSTOMER_ACTIONS
    assert gen.OPERATOR_ACTIONS == OPERATOR_ACTIONS
    assert gen.STAFF_REVIEW_ACTIONS == STAFF_REVIEW_ACTIONS
    assert gen.SPI_ACTIONS == SPI_ACTIONS
    assert gen.ENGINE_HANDLED_ACTIONS == ENGINE_HANDLED_ACTIONS
    assert gen.TS_GHOST_ACTIONS == TS_GHOST_ACTIONS
    assert gen.DEFAULT_REFUND_AUTO_APPROVAL_LIMIT == DEFAULT_REFUND_AUTO_APPROVAL_LIMIT
    assert set(gen.APPROVAL_ACTIONS) == set(ENGINE_HANDLED_ACTIONS)
