import * as fs from 'node:fs';
import * as path from 'node:path';
import { replaceKnowledgeFile } from 'engine/src/rag/updateRag';

async function main() {
  const targetFileArg = process.argv[2];
  const knowledgeDir = path.resolve(__dirname, '../../../docs/knowledge');

  console.log('=================================================');
  console.log('🔄 RAG 知识库热更新与替换工具 (RAG Knowledge Updater)');
  console.log('=================================================');

  if (targetFileArg) {
    const fullPath = path.resolve(process.cwd(), targetFileArg);
    if (!fs.existsSync(fullPath)) {
      console.error(`❌ 指定文件不存在: ${fullPath}`);
      process.exit(1);
    }
    await replaceKnowledgeFile(fullPath);
  } else {
    console.log(`正在全量扫描并热更新目录: ${knowledgeDir}...`);
    if (fs.existsSync(knowledgeDir)) {
      const files = fs.readdirSync(knowledgeDir).filter((f) => f.endsWith('.md') || f.endsWith('.txt'));

      for (const file of files) {
        const filePath = path.join(knowledgeDir, file);
        await replaceKnowledgeFile(filePath);
      }
    }
  }

  console.log('=================================================');
  console.log('✅ RAG 知识库热更新落盘完成！');
  console.log('=================================================');
}

if (import.meta.main) {
  main()
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('Update RAG Error:', err);
      process.exit(1);
    });
}
