"""视觉解析模块单测 — wayfinder multimodal-image-chat 003(移植 TS visionAnalyzerService)。

双分支验收:LLM 成功出结构化定责 / 失败(超时/异常)降级启发式;
本地图经 /api/uploads 引用解析为 base64 Data URL;PII 脱敏复用 scrubber 口径。
伪模型注入 seam:analyze_images(model=...) 的 with_structured_output 可替换。
"""

from __future__ import annotations

import asyncio

from engine_py.vision import analyze_images, normalize_image_urls
from engine_py.vision.analyzer import DamageAssessment, VisionAnalysis

_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


class _FakeStructuredRunnable:
    """伪结构化调用:记录入参消息,可抛异常或回固定 VisionAnalysis。"""

    def __init__(self, result=None, exc: Exception | None = None):
        self.result = result
        self.exc = exc
        self.captured: list = []

    async def ainvoke(self, messages, config=None, **kwargs):
        self.captured.append(messages)
        if self.exc:
            raise self.exc
        return self.result


class _FakeModel:
    def __init__(self, runnable: _FakeStructuredRunnable):
        self.runnable = runnable
        self.structured_method: str | None = None

    def with_structured_output(self, schema, method=None, **kwargs):
        self.structured_method = method
        return self.runnable


def _llm_damage_result() -> VisionAnalysis:
    return VisionAnalysis(
        visual_summary="一双运动鞋,鞋面有划痕",
        detected_objects=["sneaker", "shipping_label"],
        extracted_order_id="ORD-77889",
        extracted_tracking_number="SF9876543210",
        ocr_text="ORD-77889 SF9876543210",
        damage_assessment=DamageAssessment(
            damage_level="minor",
            summary="鞋面轻微划痕,联系电话 13812345678",
            confidence=0.92,
            suggested_action="human_review",
        ),
    )


class TestVisionAnalyzer:
    def test_no_images_returns_empty_without_calling_model(self):
        runnable = _FakeStructuredRunnable(exc=AssertionError("不应触碰模型"))
        res = asyncio.run(analyze_images([], "没图", model=_FakeModel(runnable)))
        assert res["visualSummary"] == ""
        assert res["detectedObjects"] == []
        assert res["damageAssessment"] is None
        assert runnable.captured == []

    def test_llm_failure_falls_back_to_heuristic_damage(self):
        runnable = _FakeStructuredRunnable(exc=TimeoutError("vision timeout"))
        res = asyncio.run(
            analyze_images(
                ["https://cdn.store.com/uploads/broken_shoes.jpg"],
                "鞋底脱胶开裂了,申请退货退款 ORD-77889",
                model=_FakeModel(runnable),
            )
        )
        assert res["extractedOrderId"] == "ORD-77889"
        dmg = res["damageAssessment"]
        assert dmg is not None
        assert dmg["damageLevel"] in ("minor", "severe")
        assert dmg["confidence"] == 0.88
        assert dmg["imageUrl"] == "https://cdn.store.com/uploads/broken_shoes.jpg"
        assert dmg["suggestedAction"] in ("auto_refund", "require_inspection", "human_review")

    def test_heuristic_extracts_tracking_number_regex(self):
        runnable = _FakeStructuredRunnable(exc=RuntimeError("llm down"))
        res = asyncio.run(
            analyze_images(
                ["https://cdn.store.com/uploads/label.png"],
                "这是我的快递面单 SF9876543210",
                model=_FakeModel(runnable),
            )
        )
        assert res["extractedTrackingNumber"] == "SF9876543210"

    def test_no_damage_words_no_damage_assessment(self):
        runnable = _FakeStructuredRunnable(exc=RuntimeError("llm down"))
        res = asyncio.run(
            analyze_images(["https://cdn.store.com/x.jpg"], "帮我看看这个商品", model=_FakeModel(runnable))
        )
        assert res["damageAssessment"] is None

    def test_llm_success_structured_and_pii_scrubbed(self):
        runnable = _FakeStructuredRunnable(result=_llm_damage_result())
        fake = _FakeModel(runnable)
        res = asyncio.run(
            analyze_images(["https://cdn.store.com/uploads/broken_shoes.jpg"], "鞋底脱胶 ORD-77889", model=fake)
        )
        # 结构化输出走 function_calling(001 裁决:GLM-4.6V 无 response_format)
        assert fake.structured_method == "function_calling"
        assert res["extractedOrderId"] == "ORD-77889"
        assert res["extractedTrackingNumber"] == "SF9876543210"
        assert res["visualSummary"] == "一双运动鞋,鞋面有划痕"
        dmg = res["damageAssessment"]
        assert dmg["damageLevel"] == "minor"
        assert dmg["suggestedAction"] == "human_review"
        assert dmg["confidence"] == 0.92
        # 契约字段名 camelCase(前端 DamageAssessmentCard 钉死)+ imageUrl 服务端强制回填
        assert set(dmg) == {"damageLevel", "summary", "confidence", "suggestedAction", "imageUrl"}
        assert dmg["imageUrl"] == "https://cdn.store.com/uploads/broken_shoes.jpg"
        # PII:手机号不得明文出现在任何输出文本
        assert "13812345678" not in dmg["summary"]
        assert "138****" in dmg["summary"]

    def test_local_upload_reference_resolved_to_data_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
        (tmp_path / "shot.png").write_bytes(_PNG_1PX)
        runnable = _FakeStructuredRunnable(exc=RuntimeError("降级走启发式"))
        res = asyncio.run(
            analyze_images(["/api/uploads/shot.png"], "鞋子破损了 ORD-1", model=_FakeModel(runnable))
        )
        # 发往模型的消息里,本地图必须是 base64 Data URL(bigmodel 拉不到 localhost)
        messages = runnable.captured[0]
        blocks = messages[0].content
        image_blocks = [b for b in blocks if b.get("type") == "image_url"]
        assert len(image_blocks) == 1
        assert image_blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")
        # 定责卡的 imageUrl 保持原始可访问引用,不泄漏 base64
        assert res["damageAssessment"]["imageUrl"] == "/api/uploads/shot.png"

    def test_unresolvable_local_image_degrades_without_exception(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
        runnable = _FakeStructuredRunnable(exc=AssertionError("无图可发不应调模型"))
        res = asyncio.run(
            analyze_images(["/api/uploads/missing.png"], "破损 ORD-2", model=_FakeModel(runnable))
        )
        assert runnable.captured == []
        assert res["damageAssessment"] is not None
        assert res["damageAssessment"]["imageUrl"] == "/api/uploads/missing.png"
        assert res["extractedOrderId"] == "ORD-2"


class TestNormalizeImageUrls:
    """wayfinder multimodal 005:入图归一化与限额(TS 时代零防护)。"""

    def test_caps_at_three_preserving_order(self):
        assert normalize_image_urls(["/a.png", "/b.png", "/c.png", "/d.png", "/e.png"]) == [
            "/a.png",
            "/b.png",
            "/c.png",
        ]

    def test_dedupes_and_drops_garbage(self):
        assert normalize_image_urls(
            ["  /a.png  ", "/a.png", None, "", 123, "https://cdn.example.com/b.jpg", "/a.png"]
        ) == ["/a.png", "https://cdn.example.com/b.jpg"]

    def test_none_and_empty_yield_empty_list(self):
        assert normalize_image_urls(None) == []
        assert normalize_image_urls([]) == []

    def test_default_uploads_dir_matches_gateway_layout(self, monkeypatch):
        # 默认分支必须落在仓库根 public/uploads(与 gateway 落盘同约定);
        # E2E 实测踩过 parents[4] 差一层 → services/public/uploads 偏移,图全被跳过
        import pathlib

        from engine_py.vision.analyzer import _uploads_dir

        monkeypatch.delenv("UPLOADS_DIR", raising=False)
        assert _uploads_dir() == pathlib.Path(__file__).resolve().parents[3] / "public" / "uploads"

    def test_heuristic_matches_glue_split_phrasing(self):
        # E2E 实测:「鞋底开胶断裂」不中 TS 原版词表,LLM 超时降级后定责全丢(005 修复)
        runnable = _FakeStructuredRunnable(exc=TimeoutError("vision timeout"))
        res = asyncio.run(
            analyze_images(["/api/uploads/x.png"], "鞋底开胶断裂了", model=_FakeModel(runnable))
        )
        assert res["damageAssessment"] is not None
        assert res["damageAssessment"]["damageLevel"] == "minor"
