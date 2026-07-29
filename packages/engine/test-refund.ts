import { runAgent } from './src/graph/buildGraph';

async function testRefund() {
  console.log('=== Starting Local Agent Refund Interception Test ===');
  try {
    const threadId = '1736c0c1-2f04-4fbc-8da2-573a902e0d5f';
    const userId = '83d67d4e-104c-4325-8aa7-10d4389fc725';
    const message = 'ORD-ADIDAS-AUDIT 申请退货';

    console.log(`Sending message: "${message}"`);
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

testRefund();
