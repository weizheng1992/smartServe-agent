"""图证指纹账本单测(2026-10-17 视觉加固 ②,vision/fingerprints.py + vision_parse 接线)。

四层:
1. ``evaluate_reuse`` 纯函数判定口径 —— 跨用户命中;同 URL(多轮重分析)/
   同用户(重试)/匿名先前记录不 flag;
2. ``apply_reuse_flag`` 只降级语义 —— severe+auto_refund 也压回 human_review,
   fraudFlag/fraudHits 增量键,原 dict 不变异;
3. ``audit_image_reuse`` DB 面 —— fake session 抓 SQL(租户硬条件 + ON CONFLICT
   幂等记账);DB 炸 → fail-open flagged=False 不抛;非本地图短路不触库;
4. vision_parse 接线 —— flagged → 评级降级 + record_reuse_hit 计数(calls 不增),
   未 flag 原样透传,无评级不触反查。

DB/Redis/LLM 零依赖:hash 走 tmp UPLOADS_DIR 的 1px PNG,DB 走 fake session,
反查走引擎模块 patch 缝(ctx.ns 同款)。
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from engine_py.triage import intent_triage_engine as engine_module
from engine_py.triage.intent_triage_engine import IntentTriageEngine
from engine_py.triage.stages import VisionParseStage
from engine_py.triage.stages.context import StageContext
from engine_py.vision import fingerprints, telemetry

_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def _isolate_telemetry():
    telemetry.reset_for_tests()
    yield
    telemetry.reset_for_tests()


def _totals(snapshot) -> dict:
    totals = {}
    for counts in snapshot.values():
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
    return totals


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def fetchall(self):
        return [_FakeRow(r) for r in self._rows]


class _FakeRow:
    def __init__(self, mapping: dict):
        self._mapping = mapping

    def __getattr__(self, item):  # r._mapping 由判定路径直接取用
        return self._mapping.get(item)


class _FakeSession:
    """抓 SQL 与绑定参数;SELECT 回放 canned rows(不触真库)。"""

    def __init__(self, select_rows: list[dict] | None = None, fail: Exception | None = None):
        self.statements: list[dict] = []
        self._select_rows = select_rows or []
        self._fail = fail
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params=None):
        if self._fail:
            raise self._fail
        self.statements.append({"sql": str(stmt), "params": params or {}})
        if "SELECT" in str(stmt).upper():
            return _FakeResult(self._select_rows)
        return _FakeResult([])

    async def commit(self):
        self.commits += 1


# ---- 1. evaluate_reuse 纯函数 ----


class TestEvaluateReuse:
    def test_cross_user_prior_record_hits(self):
        rows = [{"url": "/api/uploads/a.png", "user_id": "u_other", "sha256": "h1"}]
        hits = fingerprints.evaluate_reuse(rows, current_urls={"/api/uploads/b.png"}, user_id="u_me")
        assert len(hits) == 1
        assert hits[0]["priorUserId"] == "u_other" and hits[0]["sha256"] == "h1"

    def test_same_url_same_user_anonymous_do_not_hit(self):
        rows = [
            {"url": "/api/uploads/b.png", "user_id": "u_other", "sha256": "h1"},  # 同 URL=本轮重分析
            {"url": "/api/uploads/c.png", "user_id": "u_me", "sha256": "h1"},  # 同用户=重试
            {"url": "/api/uploads/d.png", "user_id": None, "sha256": "h1"},  # 匿名先前记录
        ]
        assert fingerprints.evaluate_reuse(rows, current_urls={"/api/uploads/b.png"}, user_id="u_me") == []

    def test_anonymous_current_user_cannot_flag(self):
        rows = [{"url": "/api/uploads/a.png", "user_id": "u_other", "sha256": "h1"}]
        assert fingerprints.evaluate_reuse(rows, current_urls=set(), user_id=None) == []


# ---- 2. apply_reuse_flag 只降级 ----


class TestApplyReuseFlag:
    def test_severe_auto_refund_downgraded_and_flagged(self):
        dmg = {"damageLevel": "severe", "suggestedAction": "auto_refund", "confidence": 0.95}
        flagged = fingerprints.apply_reuse_flag(dmg, hits=[{"sha256": "h1"}])
        assert flagged["suggestedAction"] == "human_review"  # 命中连 severe 也不放行秒赔展示
        assert flagged["fraudFlag"] == "reuse_cross_user"
        assert flagged["fraudHits"] == 1
        assert "fraudFlag" not in dmg  # 原 dict 不变异(终局组装器可能带原值)

    def test_human_review_stays_and_requires_inspection_downgraded(self):
        stay = fingerprints.apply_reuse_flag({"suggestedAction": "human_review"}, hits=[])
        assert stay["suggestedAction"] == "human_review"
        down = fingerprints.apply_reuse_flag({"suggestedAction": "require_inspection"}, hits=[])
        assert down["suggestedAction"] == "human_review"


# ---- 3. audit_image_reuse DB 面 ----


class TestAuditImageReuse:
    def test_hash_local_image(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
        (tmp_path / "shot.png").write_bytes(_PNG_1PX)
        digest = fingerprints._hash_local_image("/api/uploads/shot.png")
        assert digest == hashlib.sha256(_PNG_1PX).hexdigest()
        assert fingerprints._hash_local_image("/api/uploads/missing.png") is None
        assert fingerprints._hash_local_image("https://cdn.example.com/x.jpg") is None

    def test_happy_path_flags_cross_user_and_records(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
        (tmp_path / "shot.png").write_bytes(_PNG_1PX)
        digest = hashlib.sha256(_PNG_1PX).hexdigest()
        session = _FakeSession(
            select_rows=[{"url": "/api/uploads/prior.png", "user_id": "u_other", "sha256": digest}]
        )
        monkeypatch.setattr(fingerprints, "get_session", lambda: session)

        res = asyncio.run(
            fingerprints.audit_image_reuse(
                ["/api/uploads/shot.png"], user_id="u_me", business_id="aurora"
            )
        )
        assert res["flagged"] is True and len(res["hits"]) == 1
        assert res["checked"] == 1
        selects = [s for s in session.statements if "SELECT" in s["sql"]]
        inserts = [s for s in session.statements if "INSERT" in s["sql"]]
        assert len(selects) == 1 and len(inserts) == 1
        assert selects[0]["params"]["biz"] == "aurora"  # 租户硬条件
        assert selects[0]["params"]["hashes"] == [digest]
        assert inserts[0]["params"]["uid"] == "u_me"
        assert session.commits == 1  # commit 在 async-with 内(get_session 契约)

    def test_db_failure_fails_open_without_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
        (tmp_path / "shot.png").write_bytes(_PNG_1PX)
        session = _FakeSession(fail=RuntimeError("db down"))
        monkeypatch.setattr(fingerprints, "get_session", lambda: session)
        res = asyncio.run(
            fingerprints.audit_image_reuse(
                ["/api/uploads/shot.png"], user_id="u_me", business_id="aurora"
            )
        )
        assert res["flagged"] is False and res.get("degraded") is True

    def test_remote_only_urls_short_circuit_without_db(self, monkeypatch):
        session = _FakeSession(fail=AssertionError("非本地图不应触库"))
        monkeypatch.setattr(fingerprints, "get_session", lambda: session)
        res = asyncio.run(
            fingerprints.audit_image_reuse(
                ["https://cdn.example.com/x.jpg"], user_id="u_me", business_id="aurora"
            )
        )
        assert res["flagged"] is False and res["checked"] == 0


# ---- 4. vision_parse 接线 ----


def _ctx(state: dict) -> StageContext:
    return StageContext(
        state=state,
        thread_id="t-fp-1",
        input_text=state.get("input", ""),
        clean_input=state.get("input", ""),
        tenant_id="aurora",
        history_msgs=[],
        engine=IntentTriageEngine,
    )


class TestVisionParseWiring:
    def test_flagged_damage_downgraded_and_counted(self, monkeypatch):
        async def _fake_analyze(image_urls, prompt, **kwargs):
            return {"damageAssessment": {"damageLevel": "severe", "suggestedAction": "auto_refund", "confidence": 0.95}}

        async def _fake_audit(image_urls, *, user_id, business_id):
            assert business_id == "aurora" and user_id == "u_me"
            return {"flagged": True, "hits": [{"sha256": "h1", "priorUserId": "u_other"}], "checked": 1}

        monkeypatch.setattr(engine_module, "analyze_images", _fake_analyze)
        monkeypatch.setattr(engine_module, "audit_image_reuse", _fake_audit)

        ctx = _ctx({"input": "鞋坏了", "image_urls": ["/api/uploads/a.png"], "user_id": "u_me"})
        asyncio.run(VisionParseStage.judge(ctx))

        dmg = ctx.damage_assessment
        assert dmg["suggestedAction"] == "human_review"  # severe 也被复用命中压回
        assert dmg["fraudFlag"] == "reuse_cross_user"
        assert dmg["damageLevel"] == "severe"  # 等级本身不动,只降动作
        totals = _totals(telemetry.snapshot_and_reset_counters())
        assert totals["fraud_reuse_hit"] == 1
        assert totals["calls"] == 0  # 命中计数严禁虚增调用量

    def test_unflagged_damage_passthrough_untouched(self, monkeypatch):
        async def _fake_analyze(image_urls, prompt, **kwargs):
            return {"damageAssessment": {"damageLevel": "minor", "suggestedAction": "human_review", "confidence": 0.9}}

        async def _fake_audit(image_urls, *, user_id, business_id):
            return {"flagged": False, "hits": [], "checked": 1}

        monkeypatch.setattr(engine_module, "analyze_images", _fake_analyze)
        monkeypatch.setattr(engine_module, "audit_image_reuse", _fake_audit)
        ctx = _ctx({"input": "看看", "image_urls": ["/api/uploads/a.png"], "user_id": "u_me"})
        asyncio.run(VisionParseStage.judge(ctx))
        assert ctx.damage_assessment == {"damageLevel": "minor", "suggestedAction": "human_review", "confidence": 0.9}
        assert "fraudFlag" not in ctx.damage_assessment
        assert _totals(telemetry.snapshot_and_reset_counters()) == {}

    def test_no_damage_assessment_skips_audit(self, monkeypatch):
        async def _fake_analyze(image_urls, prompt, **kwargs):
            return {"damageAssessment": None}

        async def _must_not_call(image_urls, *, user_id, business_id):
            raise AssertionError("无评级(非索赔语境)不应触发指纹反查")

        monkeypatch.setattr(engine_module, "analyze_images", _fake_analyze)
        monkeypatch.setattr(engine_module, "audit_image_reuse", _must_not_call)
        ctx = _ctx({"input": "看看", "image_urls": ["/api/uploads/a.png"], "user_id": "u_me"})
        asyncio.run(VisionParseStage.judge(ctx))
        assert ctx.damage_assessment is None
        assert _totals(telemetry.snapshot_and_reset_counters()) == {}
