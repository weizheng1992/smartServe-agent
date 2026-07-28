import { db } from '../packages/db/src/index';

async function migrate() {
  console.log('=====================================================');
  console.log('[DB Migration] 🚀 Upgrading long_memory_facts schema...');
  console.log('=====================================================');

  try {
    // 1. Add confidence column
    try {
      await db.execute('ALTER TABLE "long_memory_facts" ADD COLUMN "confidence" REAL DEFAULT 1.0;');
      console.log('   ✅ Successfully added column "confidence" (REAL).');
    } catch (err: any) {
      if (err.message?.includes('already exists')) {
        console.log('   ℹ️ Column "confidence" already exists. Skipping.');
      } else {
        throw err;
      }
    }

    // 2. Add status column
    try {
      await db.execute('ALTER TABLE "long_memory_facts" ADD COLUMN "status" TEXT DEFAULT \'approved\';');
      console.log('   ✅ Successfully added column "status" (TEXT).');
    } catch (err: any) {
      if (err.message?.includes('already exists')) {
        console.log('   ℹ️ Column "status" already exists. Skipping.');
      } else {
        throw err;
      }
    }

    // 3. Add source column
    try {
      await db.execute('ALTER TABLE "long_memory_facts" ADD COLUMN "source" TEXT DEFAULT \'regex_fallback\';');
      console.log('   ✅ Successfully added column "source" (TEXT).');
    } catch (err: any) {
      if (err.message?.includes('already exists')) {
        console.log('   ℹ️ Column "source" already exists. Skipping.');
      } else {
        throw err;
      }
    }

    console.log('\n=====================================================');
    console.log('[DB Migration Complete] schema is successfully upgraded!');
    console.log('=====================================================');
  } catch (err: any) {
    console.error('\n❌ DB Migration failed:', err.message || err);
    process.exit(1);
  }
}

migrate()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
