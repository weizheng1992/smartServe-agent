"""热路径索引钉住(2026-09-27 夜审 F1;2026-10-02 夜审修复C 补 intent_logs 会话维度)。

models.py 元数据层面断言六条索引存在且列序正确 —— 防止后续改模型时
被顺手删掉而 alembic/versions/0016、0017 与实际建表漂移。列序即查询形状
(user_id 等值在前 / status 等值在前),单列索引不钉。
"""

from __future__ import annotations

import pytest

from engine_py.db.models import Base

EXPECTED = {
    "threads": {
        "threads_user_updated_idx": ["user_id", "updated_at"],
    },
    "session_metrics": {
        "session_metrics_biz_created_idx": ["business_id", "created_at"],
    },
    "intent_logs": {
        "intent_logs_created_at_idx": ["created_at"],
        "intent_logs_thread_created_idx": ["thread_id", "created_at"],
    },
    "pending_approvals": {
        "pending_approvals_status_created_idx": ["status", "created_at"],
        "pending_approvals_thread_created_idx": ["thread_id", "created_at"],
    },
}


@pytest.mark.parametrize(
    ("table", "index_name", "columns"),
    [(t, i, cols) for t, idxs in EXPECTED.items() for i, cols in idxs.items()],
)
def test_hot_path_index_pinned(table: str, index_name: str, columns: list[str]) -> None:
    indexes = {ix.name: [c.name for c in ix.columns] for ix in Base.metadata.tables[table].indexes}
    assert indexes.get(index_name) == columns, (
        f"{table}.{index_name} 缺失或列序漂移 —— 热路径会退回全表扫;"
        "如确属有意删除,请同批下线 alembic/versions/0016、0017 对应迁移"
    )


if __name__ == "__main__":
    pytest.main([__file__])
