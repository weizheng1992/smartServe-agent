# 文档 RAG 模拟样例(docs/rag-samples)

极光演示租户的**虚构**文档集,专供文档 RAG 管线(`engine_py/rag/document_*`)的
演示、评测与真弹冒烟使用。全部内容为编造的演示数据,零真实业务信息。

## 语料覆盖(与管线能力一一对应)

| 文档 | chart | 表格 | 文字数据 |
|---|---|---|---|
| 极光会员积分体系PRD.docx | ✅ 柱状图(位图) | ✅ 兑换门槛 | ✅ 清零规则 |
| 极光大促活动作战手册.docx | ✅ 折线图(位图) | ✅ 库存红线 | ✅ 客服 SOP |
| 极光物流配送说明.docx | — | ✅✅ 双表格 | ✅ 异常件条款 |
| 极光退换货政策v2.docx | — | ✅ 不予退换表 | ✅ 修订要点 |
| 极光门店巡检报告9月.pdf | ✅ 内嵌位图 | ✅ 扣分明细 | ✅ 整改要求 |
| 极光运营月报-月活图表.docx | ✅ **原生 Word 图表**(OOXML 缓存,无损提取路径) | — | ✅ 月活文字 |

## 再生成

```bash
cd services/engine-py && uv run python ../../docs/rag-samples/generate_samples.py
```

PDF 步骤自动调用 macOS Chrome(headless 打印 HTML);其他平台用任意浏览器打印
脚本产出的 `/tmp/rag_sample_report.html`。图表由 PIL 现画(中文字体走
Hiragino,非 macOS 换 `FONT` 常量)。

## 摄取入库

```bash
uv run --env-file .env python -m engine_py.rag.document_ingest docs/rag-samples --business-id aurora
```

同名文件重传 = 整组替换;清除演示数据:

```sql
DELETE FROM rag_documents WHERE source_url IN (
  '极光会员积分体系PRD.docx','极光大促活动作战手册.docx','极光物流配送说明.docx',
  '极光退换货政策v2.docx','极光门店巡检报告9月.pdf','极光运营月报-月活图表.docx');
```
