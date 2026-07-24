import { getDrizzle } from 'db';
import { getEmbeddingModel } from '../llm/callLLMWithRetry';

export interface ShortMemoryMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export class ShortMemory {
  private threadId: string;
  private maxTurns: number;

  constructor(threadId: string, maxTurns = 10) {
    this.threadId = threadId;
    this.maxTurns = maxTurns;
  }

  async getMessages(): Promise<ShortMemoryMessage[]> {
    const dbInstance = getDrizzle();
    if (dbInstance) {
      try {
        const { messages } = require('db');
        const { eq } = require('drizzle-orm');
        const rows = await dbInstance
          .select({
            role: messages.role,
            content: messages.content,
          })
          .from(messages)
          .where(eq(messages.threadId, this.threadId))
          .orderBy(messages.timestamp);
        return rows.map((msg: any) => ({
          role: msg.role as 'user' | 'assistant' | 'system',
          content: msg.content,
        }));
      } catch (err) {
        console.warn(
          '[ShortMemory] Failed to read messages from PostgreSQL via Drizzle. Falling back to core db.',
          err,
        );
      }
    }

    const { db } = require('db');
    const messages = await db.getMessages(this.threadId);
    return messages.map((msg: any) => ({
      role: msg.role as 'user' | 'assistant' | 'system',
      content: msg.content,
    }));
  }

  async addMessage(role: 'user' | 'assistant' | 'system', content: string): Promise<void> {
    const dbInstance = getDrizzle();
    const id = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).substring(2, 15);
    const timestamp = new Date().toISOString();

    if (dbInstance) {
      try {
        const { messages } = require('db');
        await dbInstance.insert(messages).values({
          id,
          threadId: this.threadId,
          role,
          content,
          timestamp,
        });
        console.log(
          `[ShortMemory] Added message directly to PostgreSQL via Drizzle: [${role}] ${content.substring(0, 50)}`,
        );
        return;
      } catch (err) {
        console.warn('[ShortMemory] Failed to insert message to PostgreSQL via Drizzle. Falling back to core db.', err);
      }
    }

    const { db } = require('db');
    await db.addMessage({
      id,
      threadId: this.threadId,
      role,
      content,
      timestamp,
    });
    console.log(`[ShortMemory] Added message for thread ${this.threadId}: [${role}] ${content.substring(0, 50)}`);
  }

  async compress(messages: ShortMemoryMessage[]): Promise<string> {
    return 'Summary of compressed conversation history';
  }
}
