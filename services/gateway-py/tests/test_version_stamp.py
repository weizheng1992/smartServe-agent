"""进程版本戳(2026-10-15 夜评台账 #3 收口):09-17/09-18/09-20 三轮
「巡检打在旧进程上」事故 —— uvicorn --reload 不监视 engine_py,手拉网关
漏带 --env-file 也照常起,巡检比对进程版本无从下手。启动时把 git SHA +
pid + 启动时刻落 /tmp/smartserve-gateway.json,巡检(与重启裁决)据此
判「网关是不是当前代码」。非 git 环境(生产容器)诚实落 unknown,不阻断启动。"""

from __future__ import annotations

import json
from pathlib import Path

from gateway_py.version_stamp import collect_stamp, write_stamp


def test_collect_stamp_has_sha_pid_started_at(monkeypatch):
    monkeypatch.setattr(
        "gateway_py.version_stamp._git_sha", lambda: "a1b2c3d"
    )
    stamp = collect_stamp()
    assert stamp["sha"] == "a1b2c3d"
    assert isinstance(stamp["pid"], int)
    assert "started_at" in stamp


def test_git_failure_degrades_to_unknown(monkeypatch):
    """生产容器无 .git:sha 落 unknown(诚实缺省),严禁抛错阻断启动。"""
    monkeypatch.setattr("gateway_py.version_stamp._git_sha", lambda: None)
    stamp = collect_stamp()
    assert stamp["sha"] == "unknown"


def test_write_stamp_persists_json(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "gateway_py.version_stamp._git_sha", lambda: "deadbee"
    )
    target = tmp_path / "stamp.json"
    stamp = write_stamp(target)
    persisted = json.loads(target.read_text())
    assert persisted["sha"] == "deadbee"
    assert persisted == stamp
