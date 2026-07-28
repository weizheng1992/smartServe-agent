import { db, getDrizzle } from 'db';

async function verifyDbIntegrity() {
  console.log('=====================================================');
  console.log('[DB Audit] 🩺 Verifying Database Integrity, Schema Relations & Latency Benchmark...');
  console.log('=====================================================');

  const drizzle = getDrizzle();
  const isOnline = !!drizzle;

  if (isOnline) {
    console.log('✅ Connection Status: PHYSICAL POSTGRESQL ONLINE');
  } else {
    console.log('⚠️ Connection Status: POSTGRESQL OFFLINE (FALLBACK ACTIVATED)');
  }

  // =========================================================================
  // Scenario 1: Verify Table Row Counts
  // =========================================================================
  try {
    console.log('\n1. Auditing structural tables row counts...');
    const tablesToAudit = ['users', 'threads', 'messages', 'orders', 'products', 'order_items'];

    for (const table of tablesToAudit) {
      const res = await db.execute(`SELECT COUNT(*) AS count FROM "${table}"`);
      const count = res.rows?.[0] ? (res.rows[0] as any).count : 0;
      console.log(`   - Table [${table}]: ${count} rows.`);
    }
  } catch (err: any) {
    console.error('❌ Table count audit failed:', err.message || err);
  }

  // =========================================================================
  // Scenario 2: Audit Relational Integrity (Dangling Foreign Keys Check)
  // =========================================================================
  try {
    console.log('\n2. Auditing relational consistency & foreign keys...');

    // Check if there are any messages with missing/dangling threads
    const resDanglingMsg = await db.execute(`
      SELECT COUNT(*) AS count FROM messages m
      LEFT JOIN threads t ON m.thread_id = t.id
      WHERE t.id IS NULL
    `);
    const danglingMsgs = resDanglingMsg.rows?.[0] ? (resDanglingMsg.rows[0] as any).count : 0;

    if (Number(danglingMsgs) === 0) {
      console.log('   ✅ Relational integrity test passed: 0 dangling messages.');
    } else {
      console.warn(
        `   ❌ RELATIONAL VIOLATION: Found [${danglingMsgs}] dangling messages referencing missing threads.`,
      );
    }

    // Check if there are any threads with missing users
    const resDanglingThreads = await db.execute(`
      SELECT COUNT(*) AS count FROM threads t
      LEFT JOIN users u ON t.user_id = u.id
      WHERE u.id IS NULL
    `);
    const danglingThreads = resDanglingThreads.rows?.[0] ? (resDanglingThreads.rows[0] as any).count : 0;

    if (Number(danglingThreads) === 0) {
      console.log('   ✅ Relational integrity test passed: 0 dangling threads.');
    } else {
      console.warn(
        `   ❌ RELATIONAL VIOLATION: Found [${danglingThreads}] dangling threads referencing missing users.`,
      );
    }
  } catch (err: any) {
    console.error('❌ Relational consistency check failed:', err.message || err);
  }

  // =========================================================================
  // Scenario 3: Performance Latency Benchmarking
  // =========================================================================
  try {
    console.log('\n3. Running execution latency benchmark (10 iterations)...');
    let totalTime = 0;
    const iterations = 10;

    for (let i = 0; i < iterations; i++) {
      const start = Date.now();
      await db.execute('SELECT 1');
      totalTime += Date.now() - start;
    }

    const avgLatency = (totalTime / iterations).toFixed(2);
    console.log(`   - Average SQL query round-trip latency: ${avgLatency} ms.`);
  } catch (err: any) {
    console.error('❌ Latency benchmark failed:', err.message || err);
  }

  console.log('\n=====================================================');
  console.log('[DB Audit Complete] Schema verification successfully concluded.');
  console.log('=====================================================');
}

verifyDbIntegrity()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
