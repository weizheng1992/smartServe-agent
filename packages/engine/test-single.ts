import { runAgent } from './src/graph/buildGraph';

async function testAgent() {
  console.log('=== Starting Local Agent Single Test ===');
  try {
    const threadId = `test_thread_${Date.now()}`;
    const userId = 'test_user_123';
    const message = 'Hello, track order ORD-98712 and check if it is shipped.';

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

testAgent();
