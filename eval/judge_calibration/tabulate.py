#!/usr/bin/env python3
"""复判表统计器(05 号票):读 calibration_sheet.md 的人工列 → judge-人一致率。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SHEET = Path(__file__).resolve().parent / "calibration_sheet.md"
THRESHOLD = 0.80


def main() -> None:
    text = SHEET.read_text(encoding="utf-8")
    blocks = re.split(r"\n## #", text)[1:]
    total = agree = unfilled = 0
    disagrees: list[str] = []
    for b in blocks:
        head, *rest = b.split("\n", 1)
        m = re.search(r"\*\*人工\*\*: (.*)", rest[0] if rest else "")
        verdict = (m.group(1) if m else "").strip()
        if not verdict:
            unfilled += 1
            continue
        total += 1
        if verdict.startswith("同意"):
            agree += 1
        else:
            disagrees.append(f"#{head.strip()} → {verdict[:80]}")
    if not total:
        raise SystemExit("复判表尚未填写(人工列全空)")
    rate = agree / total
    print(f"判次 {total} | 一致 {agree} | 一致率 {rate:.0%}(阈值 {THRESHOLD:.0%})")
    if disagrees:
        print("\n不同意清单:")
        for d in disagrees:
            print(" -", d)
    print(f"\n结论:judge {'可用' if rate >= THRESHOLD else '不可用 —— 收紧 rubric 后重测'}")
    if unfilled:
        print(f"(另有 {unfilled} 例未填,不计入)")


if __name__ == "__main__":
    main()
