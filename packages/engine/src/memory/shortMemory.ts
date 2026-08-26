import { db } from 'db';
import type { ChatMessage } from 'types';
import { sanitizeTenantResponse } from '../graph/nodes/finish.node';
import { getEmbeddingModel } from '../llm/callLLMWithRetry';

export interface ShortMemoryMessage extends ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

let lastGlobalTimestamp = 0;

function getMonotonicTimestamp(role?: 'user' | 'assistant' | 'system'): string {
  const now = Date.now();
  const roleOffset = role === 'assistant' ? 10 : role === 'system' ? 0 : 5;
  if (now <= lastGlobalTimestamp) {
    lastGlobalTimestamp += roleOffset > 0 ? roleOffset : 1;
  } else {
    lastGlobalTimestamp = now + roleOffset;
  }
  return new Date(lastGlobalTimestamp).toISOString();
}

export class ShortMemory {
  private threadId: string;
  private maxTurns: number;
  private businessId?: string;

  constructor(threadId: string, maxTurns = 10, businessId?: string) {
    this.threadId = threadId;
    this.maxTurns = maxTurns;
    if (businessId) {
      this.businessId = businessId;
    } else {
      const lower = threadId.toLowerCase();
      if (lower.includes('aurora')) this.businessId = 'aurora';
      else if (lower.includes('nike')) this.businessId = 'nike';
      else if (lower.includes('adidas')) this.businessId = 'adidas';
    }
  }

  async getMessages(): Promise<ShortMemoryMessage[]> {
    try {
      const messages = await db.getMessages(this.threadId);
      // Resolve thread businessId if available for sanitization
      let businessId = this.businessId || 'ecommerce';
      try {
        const { getDrizzle, threads } = require('db');
        const { eq } = require('drizzle-orm');
        const drizzle = getDrizzle();
        if (drizzle) {
          const threadRows = await drizzle.select().from(threads).where(eq(threads.id, this.threadId)).limit(1);
          if (threadRows[0]?.businessId) {
            businessId = threadRows[0].businessId;
          }
        }
      } catch {
        // Safe fallback
      }

      // Implement a sliding context window to fetch only the latest (maxTurns * 2) messages,
      // avoiding Context Window Bloat and reducing DB parsing and LLM token billing costs.
      const sliced = messages.slice(-this.maxTurns * 2);
      return sliced.map((msg: { role: string; content: string }) => ({
        role: msg.role as 'user' | 'assistant' | 'system',
        content: msg.role === 'assistant' ? sanitizeTenantResponse(msg.content, businessId) : msg.content,
      }));
    } catch (err) {
      console.error('[ShortMemory Error] Failed to get messages:', err);
      return [];
    }
  }

  async addMessage(role: 'user' | 'assistant' | 'system', content: string): Promise<void> {
    const id = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).substring(2, 15);
    const timestamp = getMonotonicTimestamp(role);
    const cleanContent = content !== undefined && content !== null ? String(content) : '';

    try {
      await db.createThread(this.threadId, '83d67d4e-104c-4325-8aa7-10d4389fc725', this.businessId);
      await db.addMessage({
        id,
        threadId: this.threadId,
        businessId: this.businessId,
        role,
        content: cleanContent,
        timestamp,
      } as any);
      console.log(
        `[ShortMemory] Added message for thread ${this.threadId}: [${role}] ${cleanContent.substring(0, 50)}`,
      );
    } catch (err) {
      console.error('[ShortMemory Error] Failed to add message:', err);
    }
  }

  async compress(messages: ShortMemoryMessage[]): Promise<string> {
    return 'Summary of compressed conversation history';
  }
}
