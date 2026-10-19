"""本体知识层(ADR-0015)——声明式对象-动作语义层,单一事实源。

布局与决策见 docs/adr/0015-ontology-knowledge-layer.md 与根 README「v5 规划」专节。
批〇:core + domain/marketing 试点 + 一致性门;消费方自批一(动作面)起接入。
"""

from .registry import (
    BUNDLES,
    CORE,
    ONTOLOGY_ENTITIES,
    CoreFile,
    DimensionSpec,
    DomainBundle,
    EntitySpec,
    JoinSpec,
    ValidationError,
    build_core,
    build_ontology,
    entities_of_domain,
    entity,
    semantic_dimension_projection,
    semantic_entity_projection,
    semantic_join_projection,
)

__all__ = [
    "BUNDLES",
    "CORE",
    "ONTOLOGY_ENTITIES",
    "CoreFile",
    "DimensionSpec",
    "DomainBundle",
    "EntitySpec",
    "JoinSpec",
    "ValidationError",
    "build_core",
    "build_ontology",
    "entities_of_domain",
    "entity",
    "semantic_dimension_projection",
    "semantic_entity_projection",
    "semantic_join_projection",
]
