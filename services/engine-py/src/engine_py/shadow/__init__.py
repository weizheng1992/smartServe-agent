"""影子双跑子包:回放真实会话 → 双引擎对比。"""

from .diff import diff_results
from .replay import replay_threads

__all__ = ["diff_results", "replay_threads"]
