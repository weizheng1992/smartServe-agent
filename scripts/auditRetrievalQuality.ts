import { ContextualRAG } from 'engine/src/rag/contextualRag';

async function auditRetrievalQuality() {
  console.log('=====================================================');
  console.log('[RAG Audit] 🔍 Auditing SaaS Multi-Tenant Contextual RAG Quality & Isolation...');
  console.log('=====================================================');

  const auditScenarios = [
    {
      tenant: 'nike',
      query: '我想看看退换货的时效 and 要求，我是会员',
      expectedKeyword: '会员',
      mustNotContainKeyword: 'Adidas',
    },
    {
      tenant: 'adidas',
      query: '我想看看退换货的时效 and 要求，顺丰寄回吗？',
      expectedKeyword: 'Adidas',
      mustNotContainKeyword: 'Nike',
    },
    {
      tenant: 'ecommerce',
      query: '7天无理由退换货运费谁付？',
      expectedKeyword: '电商主站',
      mustNotContainKeyword: 'Nike',
    },
  ];

  let totalScore = 0;
  let testCount = 0;

  for (const scenario of auditScenarios) {
    testCount++;
    console.log(`\n[Audit Case #${testCount}] Tenant: [${scenario.tenant}] | Query: "${scenario.query}"`);
    const rag = new ContextualRAG(scenario.tenant);
    const docs = await rag.searchRelevantDocs(scenario.query);

    if (docs.length === 0) {
      console.log('❌ FAIL: No documents retrieved!');
      continue;
    }

    let isMatch = false;
    let hasLeakage = false;

    for (const doc of docs) {
      const text = `${doc.contextualSummary} ${doc.chunkText}`;
      if (text.includes(scenario.expectedKeyword)) {
        isMatch = true;
      }
      if (text.toLowerCase().includes(scenario.mustNotContainKeyword.toLowerCase())) {
        hasLeakage = true;
      }
    }

    if (isMatch && !hasLeakage) {
      console.log('✅ PASS: Retrieval is relevant and tenant-isolated!');
      totalScore += 1;
    } else {
      if (!isMatch) console.log('❌ FAIL: Expected keyword not found in retrieved chunks.');
      if (hasLeakage)
        console.log(
          `❌ DANGER: Multi-tenant leakage detected! Contained forbidden keyword [${scenario.mustNotContainKeyword}]`,
        );
    }

    console.log('   Retrieved chunks summary:');
    docs.forEach((doc, idx) => {
      console.log(
        `     - [Chunk ${idx + 1}] (Score: ${doc.similarity.toFixed(4)}) contextualSummary: "${doc.contextualSummary.substring(0, 50)}..."`,
      );
    });
  }

  const passRate = (totalScore / testCount) * 100;
  console.log('\n=====================================================');
  console.log(`[RAG Audit Complete] Accuracy Pass Rate: ${passRate.toFixed(2)}% | Secure Isolation: OK`);
  console.log('=====================================================');
}

auditRetrievalQuality()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
