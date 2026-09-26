"""指标语义注册表契约(metrics.yaml 闭集事实源;2026-09-26 夜审 ④ 测试补强)。

37 指标 × 8 域是 Data Agent 意图层的闭集边界。此前加载校验 `_load` 的四条
响亮失败分支(条目非映射 / 缺必填键 / key 不一致 / 空注册表)零测试 ——
坏条目若被静默跳过只能靠快照计数兜底;域分布与 RBAC permissionTag 盘点
(sales_viewer 32 / warehouse_operator 3 / finance_owner 2)一并钉死,
改 YAML 必然撞到本文件,防止闭集无声漂移。
"""

from __future__ import annotations

import pytest

from engine_py.tools_registry import metric_registry
from engine_py.tools_registry.metric_registry import (
    _REQUIRED_KEYS,
    METRIC_SEMANTIC_REGISTRY,
    _load,
)

_EXPECTED_DOMAINS = {
    "sales": 13,
    "customer": 7,
    "promotion": 5,
    "inventory": 3,
    "review": 3,
    "refund": 2,
    "profit": 2,
    "session": 2,
}

_EXPECTED_TAGS = {"sales_viewer": 32, "warehouse_operator": 3, "finance_owner": 2}


class TestRegistrySnapshot:
    def test_37_metrics_closed_set(self):
        assert len(METRIC_SEMANTIC_REGISTRY) == 37, "闭集增删必须显式更新快照与规则文档"

    def test_domain_distribution_pinned(self):
        counts: dict[str, int] = {}
        for m in METRIC_SEMANTIC_REGISTRY.values():
            counts[m["domain"]] = counts.get(m["domain"], 0) + 1
        assert counts == _EXPECTED_DOMAINS

    def test_permission_tag_inventory_pinned(self):
        tags: dict[str, int] = {}
        for m in METRIC_SEMANTIC_REGISTRY.values():
            tags[m["permissionTag"]] = tags.get(m["permissionTag"], 0) + 1
        assert tags == _EXPECTED_TAGS

    def test_entries_carry_minimal_search_surface(self):
        for key, m in METRIC_SEMANTIC_REGISTRY.items():
            assert m["label"] and m["description"], f"{key}: 词面/口径描述不得为空"
            assert isinstance(m["synonyms"], list), f"{key}: synonyms 须为列表(L0 归一词表依赖)"
            assert m["direction"] in ("ASC", "DESC"), f"{key}: 排序方向越界"
            assert m["unit"], f"{key}: 单位缺失(结果卡口径注记依赖)"


def _yaml_with_all_required(entry_name: str, **overrides: str) -> str:
    fields = {
        "key": entry_name,
        "label": "总销售额 (GMV)",
        "description": "口径描述",
        "domain": "sales",
        "unit": "元",
        "direction": "DESC",
        "synonyms": "[]",
        "permissionTag": "sales_viewer",
    }
    fields.update(overrides)
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    indented = "\n".join(f"  {line}" for line in body.split("\n"))
    return f"{entry_name}:\n{indented}\n"


class TestLoadLoudFailures:
    """_load 校验分支:坏条目必须响亮失败,严禁静默跳过(08-P1 配置面纪律)。"""

    def _load_from(self, tmp_path, monkeypatch, content: str) -> dict:
        case = tmp_path / "metrics_case.yaml"
        case.write_text(content, encoding="utf-8")
        monkeypatch.setattr(metric_registry, "_YAML_PATH", case)
        return _load()

    def test_non_mapping_entry_rejected(self, tmp_path, monkeypatch):
        with pytest.raises(TypeError, match="条目必须是映射"):
            self._load_from(tmp_path, monkeypatch, "gmv: just_a_string\n")

    def test_missing_required_key_rejected(self, tmp_path, monkeypatch):
        body = _yaml_with_all_required("gmv")
        for k in _REQUIRED_KEYS:
            if k in ("key", "synonyms", "direction"):
                continue
            body = body.replace(f"  {k}:", f"  dropped_{k}:")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="缺必填键"):
            self._load_from(tmp_path, monkeypatch, body)

    def test_key_field_mismatch_rejected(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="key 字段与条目名不一致"):
            self._load_from(tmp_path, monkeypatch, _yaml_with_all_required("volume", key="gmv"))

    def test_empty_registry_rejected(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="不允许为空"):
            self._load_from(tmp_path, monkeypatch, "")

    def test_optional_keys_defaulted(self, tmp_path, monkeypatch):
        registry = self._load_from(tmp_path, monkeypatch, _yaml_with_all_required("gmv"))
        assert registry["gmv"]["aliases"] == []
        assert registry["gmv"]["conflictGroup"] == []
        assert registry["gmv"]["sampleQueries"] == []
        assert registry["gmv"]["availableDimensions"] == []
