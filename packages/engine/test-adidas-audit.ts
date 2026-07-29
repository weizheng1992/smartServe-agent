import { runAgent } from './src/graph/buildGraph';
import { db } from 'db';

async function testAdidasAudit() {
  console.log('=== Starting Test: Adidas Refund Exceeding Limit Interception ===');
  try {
    const threadId = `adidas_audit_thread_${Date.now()}`;
    const userId = '83d67d4e-104c-4325-8aa7-10d4389fc725'; // Physical seeded user possessing Adidas orders
    const message = '请帮我办理订单 ORD-ADIDAS-AUDIT 的全额退款，金额是 $179.99。';

    // 1. First, create the thread in the database explicitly under the ADIDAS businessId!
    console.log(`Creating thread [${threadId}] under business [adidas]...`);
    await db.createThread(threadId, userId, 'adidas');

    // 2. Run the agent execution flow
    console.log(`Sending message: "${message}"`);
    const result = await runAgent(threadId, userId, message);

    console.log('\n=== Success! Execution Result ===');
    console.log('Output Response:', result.output);
    console.log('Final Task Plan:', JSON.stringify(result.taskPlan, null, 2));

    // 3. Query pending_approvals to confirm it was successfully intercepted and written to Postgres!
    const approvalsRes = await db.execute(
      'SELECT id, thread_id, action_type, action_payload, status FROM pending_approvals WHERE thread_id = $1',
      [threadId]
    );

    console.log('\n=== Database pending_approvals rows for this thread ===');
    console.log(JSON.stringify(approvalsRes.rows, null, 2));

  } catch (error: any) {
    console.error('\n❌ Execution Failed with Error:');
    console.error('Message:', error.message);
    console.error('Stack:', error.stack);
  }
}

testAdidasAudit();
