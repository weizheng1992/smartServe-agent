"""本体知识层测试引导:仓库根上 sys.path(import ontology)。

批〇 不入 uv workspace(零调用方不预建装配,ADR-0015 偏差留痕)——engine_py
经 services/.venv 安装可直接 import;ontology 以仓库根路径引入。
批一接入首个消费方时,随 workspace 成员资格一并收编本引导。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
