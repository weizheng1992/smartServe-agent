import { db } from 'db';
import { runAgent } from './src/graph/buildGraph';

async function testTwoTurns() {
  console.log('=== Starting End-to-End Two-Turn Conversation Test ===');
  const threadId = `test_thread_two_turns_${Date.now()}`;
  const userId = '83d67d4e-104c-4325-8aa7-10d4389fc725'; // Seeds valid user

  try {
    // Turn 1
    console.log('\n--- TURN 1: Ask to track order ORD-98712 ---');
    const msg1 = '帮我查下 ORD-98712 的发货状态';
    console.log(`User: "${msg1}"`);
    const result1 = await runAgent(threadId, userId, msg1);
    console.log('\nAgent Response 1:\n', result1.output);

    // Turn 2
    console.log('\n--- TURN 2: Request refund (No order ID mentioned) ---');
    const msg2 = '帮我申请退货';
    console.log(`User: "${msg2}"`);
    const result2 = await runAgent(threadId, userId, msg2);
    console.log('\nAgent Response 2:\n', result2.output);
    console.log('Final Task Plan 2:\n', JSON.stringify(result2.taskPlan, null, 2));

    // Verify DB update
    console.log('\n--- DATABASE VERIFICATION ---');
    const order = await db.getOrder('ORD-98712');
    console.log('Physical order state for ORD-98712 in database:', order);
  } catch (error: any) {
    console.error('\n❌ Execution Failed with Error:');
    console.error('Message:', error.message);
    console.error('Stack:', error.stack);
  }
}

testTwoTurns();
