"""图商品真伪窄判定单测(2026-10-17 视觉加固 ③,vision/product_verify.py)。

钉死:闭集 schema 走 function_calling(GLM-4.6V 无 response_format)、本地图
转 Data URL(analyzer 同源 `_to_llm_image_url`)、图不可读/无图/模型异常 →
degraded 降级(永不抛)、阈值判定(match=yes 且 confidence ≥ 阈值)。
"""

from __future__ import annotations

import asyncio

from engine_py.vision.product_verify import ProductVerifyVerdict, verify_product_match

_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


class _FakeStructured:
    def __init__(self, result=None, exc: Exception | None = None):
        self._result = result
        self._exc = exc
        self.captured: list = []

    async def ainvoke(self, messages, config=None, **kwargs):
        self.captured.append(messages)
        if self._exc:
            raise self._exc
        return self._result


class _FakeVisionModel:
    def __init__(self, runnable: _FakeStructured):
        self.runnable = runnable

    def with_structured_output(self, schema, method=None, **kwargs):
        self.method = method
        return self.runnable


def test_verify_pass_and_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    (tmp_path / "shot.png").write_bytes(_PNG_1PX)
    runnable = _FakeStructured(
        ProductVerifyVerdict(match="yes", confidence=0.9),
    )
    model = _FakeVisionModel(runnable)
    res = asyncio.run(
        verify_product_match(
            ["/api/uploads/shot.png"], "Nike Air 红色运动鞋", model=model
        )
    )
    assert res == {"verified": True, "confidence": 0.9, "degraded": False}
    # 消息形状:文本 prompt(含商品名)+ 一张图;闭集 schema function_calling
    assert model.method == "function_calling"
    blocks = runnable.captured[0][0].content
    assert blocks[0]["type"] == "text" and "Nike Air 红色运动鞋" in blocks[0]["text"]
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_verify_low_confidence_is_not_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    (tmp_path / "shot.png").write_bytes(_PNG_1PX)
    res = asyncio.run(
        verify_product_match(
            ["/api/uploads/shot.png"],
            "Nike Air 红色运动鞋",
            model=_FakeVisionModel(_FakeStructured(ProductVerifyVerdict(match="yes", confidence=0.4))),
        )
    )
    assert res["verified"] is False and res["degraded"] is False


def test_verify_no_answer_is_not_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    (tmp_path / "shot.png").write_bytes(_PNG_1PX)
    res = asyncio.run(
        verify_product_match(
            ["/api/uploads/shot.png"],
            "玻璃茶具套装",
            model=_FakeVisionModel(_FakeStructured(ProductVerifyVerdict(match="no", confidence=0.95))),
        )
    )
    assert res["verified"] is False


def test_verify_degraded_paths_never_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    # 无图
    assert asyncio.run(verify_product_match([], "x"))["degraded"] is True
    # 图不可读(文件缺失)
    assert asyncio.run(verify_product_match(["/api/uploads/missing.png"], "x"))["degraded"] is True
    # 模型异常
    res = asyncio.run(
        verify_product_match(
            ["/api/uploads/shot.png"],
            "x",
            model=_FakeVisionModel(_FakeStructured(exc=RuntimeError("vision down"))),
        )
    )
    assert res["degraded"] is True and res["verified"] is None
