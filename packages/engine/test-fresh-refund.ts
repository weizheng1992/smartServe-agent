import { runAgent } from './src/graph/buildGraph';

async function testFreshRefund() {
  console.log('=== Starting Fresh Local Agent Refund Interception Test ===');
  try {
    const threadId = `adidas_fresh_thread_${Date.now()}`;
    const userId = '83d67d4e-104c-4325-8aa7-10d4389fc725'; // Uses the user with Adidas orders
    const message = '请帮我将订单 ORD-ADIDAS-AUDIT 申请退货。';

    console.log(`Sending message to fresh thread [${threadId}]: "${message}"`);
    const result = await runAgent(threadId, userId, message);

    console.log('\n=== Success! Execution Result ===');
    console.log('Output Response:', result.output);
    console.log('Final Task Plan:', JSON.stringify(result.taskPlan, null, 2));
  } catch (error: any) {
    console.error('\n❌ Execution Failed with Error:');
    console.error('Message:', error.message);
    console.error('Stack:', error.stack);
  }
}

testFreshRefund();
