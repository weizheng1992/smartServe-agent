"""文档知识来源卡契约(document_source)— 富卡片回显(v2,2026-10-17)。

钉死:富媒体切片(图/表)才出卡、纯文本命中零卡(引用在正文,卡是富媒体
增量)、图片 ≤3 张、来源 ≤4 条、去重、provenance 透传(vlm/extracted 前端
须带读数误差提示)。纯函数直测合成器,零 DB 零 LLM。
"""

from engine_py.cards.card_synthesizer import CardSynthesizer, _build_document_sources


def _image_doc(url: str = "/api/uploads/rag/a.png", title: str = "极光PRD", path: str = "季度目标") -> dict:
    return {
        "chunkText": "文档插图:柱状图",
        "docTitle": title,
        "headerPath": path,
        "similarity": 0.8,
        "metadata": {"contentType": "image", "imageUrl": url},
    }


def test_rich_media_hits_produce_document_source_card():
    docs = [
        _image_doc(),
        {
            "chunkText": "| 项目 | 数量 |\n| --- | --- |\n| 门店数 | 5 |",
            "docTitle": "运营月报",
            "headerPath": "月活图表",
            "similarity": 0.7,
            "metadata": {"contentType": "table"},
        },
    ]
    cards = CardSynthesizer.synthesize_cards(
        {"taskPlan": {}, "intents": [], "ragDocuments": docs, "existingCards": [], "shelfCategories": []}
    )
    source_cards = [c for c in cards if c.get("type") == "document_source"]
    assert len(source_cards) == 1, "富媒体命中恰出一卡"
    data = source_cards[0]["data"]
    assert data["title"] == "文档知识来源"
    assert len(data["sources"]) == 2
    assert data["sources"][0]["imageUrl"] == "/api/uploads/rag/a.png"
    assert data["sources"][1]["tableMarkdown"].startswith("| 项目 |"), "表格切片原文可直接渲染"
    assert data["sources"][1]["provenance"] == "native", (
        "表格切片 = docling 确定性解析零读数误差,provenance 闭集 'native'|'extracted'|'vlm'"
        "(types 契约),漏出集外值前端徽章静默丢失"
    )


def test_text_only_hits_produce_no_card():
    """纯文本文档命中:引用已在正文,卡是富媒体增量 —— 零卡严禁凑数。"""
    docs = [
        {
            "chunkText": "签收后 15 天内可无理由退货。",
            "docTitle": "退换货政策",
            "headerPath": "退货时效",
            "similarity": 0.8,
            "metadata": {"contentType": "text"},
        }
    ]
    cards = CardSynthesizer.synthesize_cards(
        {"taskPlan": {}, "intents": [], "ragDocuments": docs, "existingCards": [], "shelfCategories": []}
    )
    assert all(c.get("type") != "document_source" for c in cards)


def test_image_cap_and_dedupe():
    """图片 ≤3 张(normalize_image_urls 同纪律);同文档同章节同类型去重。"""
    docs = [_image_doc(f"/api/uploads/rag/{i}.png", path=f"章节{i}") for i in range(5)]
    sources = _build_document_sources(docs)
    assert len([s for s in sources if s["imageUrl"]]) == 3, "图片上限 3 张"
    docs_dup = [_image_doc("/api/uploads/rag/dup.png")] * 2  # 同文档同章节同类型 = 重复项
    assert len(_build_document_sources(docs_dup)) == 1, "重复项去重"


def test_provenance_passthrough_for_error_annotation():
    """provenance 原样透传:extracted/vlm 前端必须带读数误差提示(诚实律)。"""
    docs = [
        {
            "chunkText": "文档插图:巡检达标率柱状图",
            "docTitle": "巡检报告",
            "headerPath": "达标率",
            "similarity": 0.8,
            "metadata": {
                "contentType": "image",
                "imageUrl": "/api/uploads/rag/x.png",
                "chartData": {"headers": ["门店", "达标率"], "rows": [["万象城", "76"]], "provenance": "extracted"},
            },
        }
    ]
    sources = _build_document_sources(docs)
    assert sources[0]["provenance"] == "extracted"


def test_card_placement_after_domain_cards_and_before_capsule():
    """document_source 在域卡之后、quick_replies 胶囊之前(装配序契约)。"""
    docs = [_image_doc()]
    cards = CardSynthesizer.synthesize_cards(
        {
            "taskPlan": {},
            "intents": [],
            "damageAssessment": {"damageLevel": "minor"},
            "ragDocuments": docs,
            "existingCards": [],
            "shelfCategories": [],
        }
    )
    types = [c.get("type") for c in cards]
    assert "damage_assessment" in types and "document_source" in types
    assert types.index("damage_assessment") < types.index("document_source"), "域卡优先作基座"
    assert types[-1] == "quick_replies", "胶囊恒居尾(first-wins 场景除外)"
