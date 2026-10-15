"""进程版本戳(2026-10-15 夜评台账 #3):启动时把「这个网关进程跑的是哪份
代码」落到固定路径,巡检/重启裁决据此判新旧 —— uvicorn --reload 不监视
engine_py,手拉漏 --env-file 也照常起,此前三轮「巡检打在旧进程上」事故
均因进程版本无从比对。

- ``collect_stamp``:git SHA(非 git 环境诚实落 unknown)+ pid + 启动时刻;
- ``write_stamp``:落 JSON 到 /tmp/smartserve-gateway.json(路径可注入,
  测试/部署覆写),失败只 print 不阻断启动 —— 戳是观测辅助,不是业务闸。"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
from pathlib import Path

STAMP_PATH = Path("/tmp/smartserve-gateway.json")


def _git_sha() -> str | None:
    """当前工作树 HEAD 短 SHA;非 git 环境(生产容器/裸目录)返回 None。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return (out.stdout or "").strip() or None
    except Exception:
        return None


def collect_stamp() -> dict:
    return {
        "sha": _git_sha() or "unknown",
        "pid": __import__("os").getpid(),
        "started_at": _dt.datetime.now(_dt.UTC).isoformat(),
    }


def write_stamp(path: Path | None = None) -> dict:
    stamp = collect_stamp()
    target = path or STAMP_PATH
    try:
        target.write_text(json.dumps(stamp, ensure_ascii=False))
        print(f"[Startup] 版本戳已落 {target}: sha={stamp['sha']} pid={stamp['pid']}")
    except Exception as err:
        print(f"[Startup] 版本戳落盘失败(不阻断启动): {err}")
    return stamp
