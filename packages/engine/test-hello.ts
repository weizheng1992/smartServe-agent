import { runAgent } from './src/graph/buildGraph';

async function testHello() {
  console.log('=== Measuring "您好" execution latency ===');
  const start = Date.now();

  const threadId = `test_hello_lat_${Date.now()}`;
  const userId = 'test_hello_user';

  try {
    const result = await runAgent(threadId, userId, '您好');
    const duration = (Date.now() - start) / 1000;
    console.log(`=== DONE in ${duration.toFixed(2)} seconds ===`);
    console.log('Response was:', result.output);
  } catch (err: any) {
    console.error('Failed to run test:', err);
  }
}

testHello();
