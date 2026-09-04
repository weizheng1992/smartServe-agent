"""engine-py 测试共享夹具。

准则 5(见 .claude/rules/agent-engine.md):config.py 导入时读取环境变量,
任何测试基建必须先注入 DATABASE_URL / REDIS_URL 再导入 engine_py 模块。
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/test_unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
