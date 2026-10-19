# ontology/ 本体知识层

声明式对象-动作语义层(ADR-0015)——领域知识(实体/动作/校验/指标)的单一事实源。
完整方案(为什么/重构成什么/四批路径/技术选型与边界)见根 README「🧬 v5 规划」专节与
[ADR-0015](../docs/adr/0015-ontology-knowledge-layer.md)。

## 布局

```text
core.yaml            闭集词汇:domains / databases / faces
domain/*.yaml        领域层(批〇:marketing 试点;批一:四域全量)
application/*.yaml   应用层(批一:actions 动作面 / intents / metrics)
registry.py          pydantic v2 声明模型 + 加载校验 + 编译投影
generated/           双语代码生成物(批二)
cards/               LLM 接地 schema 卡(批二,由 domain 层派生)
exports/             可选导出面:property-graph schema / JSON-LD / MCP 工具面
tests/               一致性门(parity + 校验负例)
```

## 运行测试

```bash
DATABASE_URL='postgresql://u:p@localhost:5432/x' REDIS_URL='redis://localhost:6379/0' \
  services/.venv/bin/python -m pytest ontology/tests -q
```

(parity 册 import engine semantic_model,需占位 env;批〇 未入 uv workspace,
tests/conftest.py 上仓库根路径——批一首个消费方接入时收编,见 ADR-0015 偏差留痕。)

## 分层裁定

平台级一份本体(租户差异留 tenant_configs,商城/后台 = faces 曝光面);
业务数据永远留 PG(声明层零复制);动态词汇(货架品类词)运行时跟库。
