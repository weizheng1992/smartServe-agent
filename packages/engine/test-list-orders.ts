import { runAgent } from './src/graph/buildGraph';

async function testListOrders() {
  console.log('=== Starting Order List Capability Test ===');
  const threadId = `test_thread_list_orders_${Date.now()}`;
  const userId = '83d67d4e-104c-4325-8aa7-10d4389fc725'; // Mapped to u_default_id in FakePool

  try {
    const msg = '我还有其他订单吗';
    console.log(`User: "${msg}"`);
    const result = await runAgent(threadId, userId, msg);
    console.log('\nAgent Response:\n', result.output);
    console.log('\nTask Plan:\n', JSON.stringify(result.taskPlan, null, 2));
  } catch (error: any) {
    console.error('❌ Test Failed:', error);
  }
}

testListOrders();
