"""影子双跑子包:回放真实会话 → 双引擎对比。"""

from .replay import replay_threads
from .diff import diff_results

__all__ = ["replay_threads", "diff_results"]
