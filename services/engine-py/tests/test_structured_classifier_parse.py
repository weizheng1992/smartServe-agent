"""回归:结构化分类器对 LLM 输出漂移的自修复解析。

背景 bug(2026-09-04 生产日志)两类:
- [StructuredClassifier] ... Invalid JSON ... input_value='```json\\n{...}\\n```'
  (provider 返回围栏 JSON,结构化解析层直接失败)
- IntentTriageEngine Step 3 ... executionMode input_value='single' + intents Field required
  (fallback 重新问询后模型字段漂移:单意图平铺 category、自造枚举 'single')
"""

from __future__ import annotations

import pytest

from engine_py.triage.structured_classifier import (
    coerce_structured_payload,
    parse_structured_output_text,
    strip_code_fences,
)

# 日志原文:input_value='```json\\n{\\n  "intent": ...nMessage": null\\n}\\n```'
LOG_FENCED_TEXT = (
    '```json\n{\n  "intent": "cart_manage",\n  "executionMode": "single",\n'
    '  "clarificationMessage": null\n}\n```'
)

# 日志原文(去围栏后的真实 dict):{'category': 'cart_manage...', ..., 'clarificationMessage': None}
LOG_DRIFTED_PAYLOAD = {
    "category": "cart_manage",
    "confidence": 0.9,
    "entities": {"orderId": None},
    "slots": {},
    "missingSlots": ["orderId"],
    "executionMode": "single",
    "clarificationMessage": None,
}


def test_parse_log_captured_fenced_json() -> None:
    """日志捕获的围栏 JSON 必须解析成功(bug 时 json_invalid)。"""
    out = parse_structured_output_text(LOG_FENCED_TEXT)
    assert out.intents[0].intent == "cart_manage"
    assert out.executionMode == "sequential"  # 'single' 归一为合法枚举


def test_coerce_log_captured_drifted_dict() -> None:
    """日志捕获的字段漂移 dict 必须归一通过校验(bug 时 2 validation errors)。"""
    from engine_py.triage.structured_classifier import StructuredTriageOutput

    out = StructuredTriageOutput.model_validate(coerce_structured_payload(dict(LOG_DRIFTED_PAYLOAD)))
    assert out.intents[0].intent == "cart_manage"  # category → intents[].intent
    assert out.intents[0].missingSlots == ["orderId"]  # 槽位字段不丢失
    assert out.executionMode == "sequential"


def test_strip_code_fences_variants() -> None:
    assert strip_code_fences("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert strip_code_fences("```\n{\"a\": 1}\n```") == '{"a": 1}'  # 无 json 标签
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'  # 干净输出原样保留


def test_parse_tolerates_surrounding_prose() -> None:
    """fallback 应答可能附带说明文字,截取首个 JSON 对象。"""
    out = parse_structured_output_text(f"好的,以下是结果:\n{LOG_FENCED_TEXT}\n以上仅供参考。")
    assert out.intents[0].intent == "cart_manage"


@pytest.mark.parametrize(
    ("raw_mode", "expected"),
    [
        ("single", "sequential"),
        ("single_intent", "sequential"),
        ("auto", "parallel"),
        ("SEQUENTIAL", "sequential"),  # 大小写归一
        ("随便写的", "parallel"),  # 未知值回退 schema 默认
        (None, "parallel"),  # 缺省
    ],
)
def test_coerce_execution_mode_aliases(raw_mode: str | None, expected: str) -> None:
    data = coerce_structured_payload({"intent": "order_status", "executionMode": raw_mode})
    assert data["executionMode"] == expected


def test_coerce_category_inside_intents_list() -> None:
    """列表内节点用 category 代替 intent 的情况。"""
    data = coerce_structured_payload({"intents": [{"category": "refund", "confidence": 0.8}]})
    assert data["intents"][0]["intent"] == "refund"
    assert "category" not in data["intents"][0]


def test_parse_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="no JSON object"):
        parse_structured_output_text("抱歉,我不知道你在说什么。")
