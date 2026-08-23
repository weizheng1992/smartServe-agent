import { Client } from 'pg';

export interface CleanResult {
  invalidEmbeddingsDeleted: number;
  duplicateRagDocsDeleted: number;
}

export async function cleanDatabase(connectionString?: string): Promise<CleanResult> {
  const dbUrl =
    connectionString ||
    process.env.DATABASE_URL ||
    'postgres://agent_user:agent_password@localhost:5432/agent_platform';
  console.log('🔍 [Database Cleaner] Connecting to database:', dbUrl);

  const client = new Client({ connectionString: dbUrl });
  let invalidEmbeddingsDeleted = 0;
  let duplicateRagDocsDeleted = 0;

  try {
    await client.connect();
    console.log('✅ Connected to database.');

    const tables = ['long_memory_facts', 'episodic_events', 'rag_documents'];

    // 1. 清理全 0 或格式损坏的非法 embedding
    for (const table of tables) {
      console.log(`\n=== Checking invalid embeddings in table: ${table} ===`);
      try {
        const tableCheck = await client.query(
          'SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)',
          [table],
        );

        if (!tableCheck.rows[0].exists) {
          console.log(`⚠️ Table ${table} does not exist. Skipping.`);
          continue;
        }

        const res = await client.query(`SELECT id, embedding FROM ${table}`);
        console.log(`Found ${res.rows.length} total rows in ${table}.`);

        const idsToDelete: string[] = [];

        for (const row of res.rows) {
          const embeddingStr = row.embedding;
          if (!embeddingStr) {
            continue;
          }

          try {
            const vector = JSON.parse(embeddingStr);
            if (Array.isArray(vector)) {
              const isAllZeros = vector.length === 0 || vector.every((x) => x === 0);
              if (isAllZeros) {
                idsToDelete.push(row.id);
              }
            }
          } catch {
            console.log(`Malformed embedding JSON for row ID ${row.id}:`, embeddingStr.substring(0, 50));
            idsToDelete.push(row.id);
          }
        }

        if (idsToDelete.length > 0) {
          console.log(`Deleting ${idsToDelete.length} invalid rows from ${table}...`);
          const deleteRes = await client.query(`DELETE FROM ${table} WHERE id = ANY($1::uuid[])`, [idsToDelete]);
          console.log(`✅ Successfully deleted ${deleteRes.rowCount} rows from ${table}.`);
          invalidEmbeddingsDeleted += deleteRes.rowCount || 0;
        } else {
          console.log(`No invalid embeddings found in ${table}.`);
        }
      } catch (tableErr: unknown) {
        const tableMsg = tableErr instanceof Error ? tableErr.message : String(tableErr);
        console.error(`Error checking embeddings in table ${table}:`, tableMsg);
      }
    }

    // 2. 清理 rag_documents 表中的重复数据 (按 business_id 与 chunk_text 分组去重)
    console.log('\n=== Checking duplicate rows in rag_documents ===');
    try {
      const dupQuery = `
        SELECT business_id, chunk_text, count(*) as cnt,
               array_agg(id ORDER BY
                 (CASE WHEN embedding IS NOT NULL AND embedding != '' THEN 1 ELSE 0 END) DESC,
                 (CASE WHEN contextual_summary IS NOT NULL AND contextual_summary != '' THEN 1 ELSE 0 END) DESC,
                 (CASE WHEN source_url IS NOT NULL AND source_url != '' THEN 1 ELSE 0 END) DESC,
                 created_at DESC
               ) as ids
        FROM rag_documents
        GROUP BY business_id, chunk_text
        HAVING count(*) > 1
      `;
      const dupRes = await client.query(dupQuery);
      console.log(`Found ${dupRes.rows.length} groups of duplicate chunk_text in rag_documents.`);

      const dupIdsToDelete: string[] = [];
      for (const row of dupRes.rows) {
        const ids = row.ids as string[];
        if (ids && ids.length > 1) {
          // 保留排序第一条质量最好且最新的记录，删除其余冗余记录
          const toDelete = ids.slice(1);
          dupIdsToDelete.push(...toDelete);
        }
      }

      if (dupIdsToDelete.length > 0) {
        console.log(`Deleting ${dupIdsToDelete.length} duplicate rows from rag_documents...`);
        const deleteDupRes = await client.query('DELETE FROM rag_documents WHERE id = ANY($1::uuid[])', [
          dupIdsToDelete,
        ]);
        console.log(`✅ Successfully deleted ${deleteDupRes.rowCount} duplicate rows from rag_documents.`);
        duplicateRagDocsDeleted += deleteDupRes.rowCount || 0;
      } else {
        console.log('No duplicate rows found in rag_documents.');
      }
    } catch (dupErr: unknown) {
      const dupMsg = dupErr instanceof Error ? dupErr.message : String(dupErr);
      console.error('Error deduplicating rag_documents:', dupMsg);
    }

    console.log(
      `\n🎉 [Database Cleaner] Finished! Invalid embeddings deleted: ${invalidEmbeddingsDeleted}, Duplicate RAG rows deleted: ${duplicateRagDocsDeleted}`,
    );
    await client.end();
    return { invalidEmbeddingsDeleted, duplicateRagDocsDeleted };
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error('❌ Database connection failed:', errMsg);
    try {
      await client.end();
    } catch {}
    throw err;
  }
}

if (import.meta.main) {
  cleanDatabase()
    .then(() => process.exit(0))
    .catch(() => process.exit(1));
}
