import { getDrizzle, ragDocuments } from 'db';

async function inspectRAG() {
  console.log('=== Inspecting Physical RAG Documents ===');
  const drizzle = getDrizzle();
  if (!drizzle) {
    console.error('Database connection failed.');
    return;
  }

  try {
    const rows = await drizzle.select().from(ragDocuments);
    console.log(`Total rows in rag_documents: ${rows.length}`);
    for (const row of rows) {
      let embLen = 0;
      if (row.embedding) {
        try {
          const arr = JSON.parse(row.embedding);
          embLen = arr.length;
        } catch {
          embLen = -1;
        }
      }
      console.log(
        `- ID: ${row.id}, Business: ${row.businessId}, Text: "${row.chunkText.substring(0, 30)}...", Embedding Length: ${embLen}`,
      );
    }
  } catch (err: any) {
    console.error('Error during query:', err.message);
  }
}

inspectRAG();
