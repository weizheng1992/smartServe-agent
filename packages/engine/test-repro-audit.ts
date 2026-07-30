import { runAgent } from './src/graph/buildGraph';

async function test() {
  const threadId = 'test_thread_audit_repro';
  const userId = '83d67d4e-104c-4325-8aa7-10d4389fc725'; // Test user ID
  const message = '帮我申请订单 ORD-ECO-AUDIT 的退款';

  console.log(`🚀 Running runAgent for repro...`);
  try {
    const result = await runAgent(threadId, userId, message, 'test_job_123');
    console.log(`\n================ RESULT ================`);
    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    console.error('Error running agent:', err);
  }
}

test();
