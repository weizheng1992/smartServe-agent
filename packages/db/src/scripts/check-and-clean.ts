import { Client } from "pg";

async function main() {
  const dbUrl =
    process.env.DATABASE_URL ||
    "postgres://agent_user:agent_password@localhost:5432/agent_platform";
  console.log("🔍 [Embedding Cleaner] Connecting to database:", dbUrl);

  const client = new Client({ connectionString: dbUrl });

  try {
    await client.connect();
    console.log("✅ Connected to database.");

    const tables = ["long_memory_facts", "episodic_events", "rag_documents"];
    let totalDeleted = 0;

    for (const table of tables) {
      console.log(`\n=== Checking table: ${table} ===`);

      // Select all rows from the table to inspect their embeddings
      // We check if the table exists first
      try {
        const tableCheck = await client.query(
          "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)",
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
              const isAllZeros =
                vector.length === 0 || vector.every((x) => x === 0);
              if (isAllZeros) {
                idsToDelete.push(row.id);
              }
            }
          } catch (err) {
            // If it's not valid JSON, it might be a malformed embedding as well
            console.log(
              `Malformed embedding JSON for row ID ${row.id}:`,
              embeddingStr.substring(0, 50),
            );
            idsToDelete.push(row.id);
          }
        }

        console.log(
          `Identified ${idsToDelete.length} rows with invalid (all-zeros or malformed) embeddings in ${table}.`,
        );

        if (idsToDelete.length > 0) {
          console.log(
            `Deleting ${idsToDelete.length} invalid rows from ${table}...`,
          );
          // Delete in batches or using IN clause
          const deleteRes = await client.query(
            `DELETE FROM ${table} WHERE id = ANY($1::uuid[])`,
            [idsToDelete],
          );
          console.log(
            `✅ Successfully deleted ${deleteRes.rowCount} rows from ${table}.`,
          );
          totalDeleted += deleteRes.rowCount || 0;
        } else {
          console.log(`No invalid embeddings found in ${table}.`);
        }
      } catch (tableErr: unknown) {
        const tableMsg =
          tableErr instanceof Error ? tableErr.message : String(tableErr);
        console.error(`Error processing table ${table}:`, tableMsg);
      }
    }

    console.log(
      `\n🎉 [Embedding Cleaner] Finished cleanup! Total rows deleted across all tables: ${totalDeleted}`,
    );
    await client.end();
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error("❌ Database connection failed:", errMsg);
    try {
      await client.end();
    } catch {}
  }
}

main();
