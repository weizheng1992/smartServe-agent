"""促销语义内核单册(2026-10-03 收口):生效态/窗口谓词/时钟的唯一出处。

promotions.py(写面)与 promotion_engine.py(读面)此前各持一份时钟与一套
「还活着」判定,_in_window 用 now > end 而 SQL 闸用 end_at > NOW(),now==end
瞬时两套口径互相矛盾(候选集恒经 SQL 闸预过滤故分歧不可达,归一无行为变化)。
本册钉死归一后的边界契约 —— 改口径先改这里,再改本册。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from engine_py.analytics.promo_kernel import effective_status, in_window, utcnow


def _ts(day: int) -> datetime:
    # fromisoformat 产 naive:UTC-naive 是与库钟同源的契约(DTZ 闸对显式
    # 构造器拦 tzinfo 缺失,解析器无此歧义)
    return datetime.fromisoformat(f"2026-09-{day:02d}T00:00:00")


class TestEffectiveStatus:
    """展示口径:disabled > ended > scheduled > running;边界随 SQL 闸。"""

    @pytest.mark.parametrize(
        ("status", "now", "expected"),
        [
            ("disabled", _ts(15), "disabled"),  # disabled 压倒一切窗口态
            ("active", _ts(10), "scheduled"),  # now < start
            ("active", _ts(20), "running"),  # start ≤ now < end
            ("active", _ts(25), "ended"),  # now ≥ end
        ],
    )
    def test_matrix(self, status, now, expected):
        assert effective_status(status, _ts(15), _ts(25), now) == expected

    def test_boundary_now_equals_end_is_ended(self):
        """now == end_at → ended(与 SQL 闸 end_at > NOW() 同判出窗)。"""
        assert effective_status("active", _ts(15), _ts(25), _ts(25)) == "ended"

    def test_boundary_now_equals_start_is_running(self):
        assert effective_status("active", _ts(15), _ts(25), _ts(15)) == "running"

    def test_open_window(self):
        assert effective_status("active", None, None, _ts(20)) == "running"
        assert effective_status("active", _ts(15), None, _ts(20)) == "running"
        assert effective_status("active", None, _ts(25), _ts(20)) == "running"


class TestInWindow:
    """结算候选复检口径:start_at ≤ now < end_at。"""

    PROMO = {"start_at": _ts(15), "end_at": _ts(25)}

    def test_inside_window(self):
        assert in_window(self.PROMO, _ts(20)) is True

    def test_boundary_now_equals_start_included(self):
        assert in_window(self.PROMO, _ts(15)) is True

    def test_boundary_now_equals_end_excluded(self):
        """与 fetch_active_promos 的 SQL 闸(end_at > NOW())边界严格一致 ——
        收口前 _in_window 用 now > end,now==end 瞬时与 SQL 闸互相矛盾。"""
        assert in_window(self.PROMO, _ts(25)) is False

    def test_before_start_and_after_end(self):
        assert in_window(self.PROMO, _ts(10)) is False
        assert in_window(self.PROMO, _ts(26)) is False

    def test_open_window_promo(self):
        assert in_window({"start_at": None, "end_at": None}, _ts(20)) is True


class TestUtcnow:
    def test_utc_naive_same_source_as_db_clock(self):
        """列默认 NOW() 落 naive UTC;本地 naive now 在非 UTC 部署偏整时区
        (2026-09-29 夜审 F15 实弹)—— 内核钟必须 UTC-naive。"""
        now = utcnow()
        assert now.tzinfo is None
        assert abs(now - datetime.now(UTC).replace(tzinfo=None)) < timedelta(seconds=5)
