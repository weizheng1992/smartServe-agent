import { db } from "db";
import type { ChatMessage } from "types";
import { getEmbeddingModel } from "../llm/callLLMWithRetry";

export interface ShortMemoryMessage extends ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

let lastGlobalTimestamp = 0;

function getMonotonicTimestamp(): string {
  const now = Date.now();
  if (now <= lastGlobalTimestamp) {
    lastGlobalTimestamp += 1;
  } else {
    lastGlobalTimestamp = now;
  }
  return new Date(lastGlobalTimestamp).toISOString();
}

export class ShortMemory {
  private threadId: string;
  private maxTurns: number;

  constructor(threadId: string, maxTurns = 10) {
    this.threadId = threadId;
    this.maxTurns = maxTurns;
  }

  async getMessages(): Promise<ShortMemoryMessage[]> {
    try {
      const messages = await db.getMessages(this.threadId);
      // Resolve thread businessId if available for sanitization
      let businessId = "ecommerce";
      try {
        const { getDrizzle, threads } = require("db");
        const { eq } = require("drizzle-orm");
        const drizzle = getDrizzle();
        if (drizzle) {
          const threadRows = await drizzle
            .select()
            .from(threads)
            .where(eq(threads.id, this.threadId))
            .limit(1);
          if (threadRows[0]?.businessId) {
            businessId = threadRows[0].businessId;
          }
        }
      } catch {
        // Safe fallback
      }

      const { sanitizeTenantResponse } = require("../graph/nodes/finish.node");
      // Implement a sliding context window to fetch only the latest (maxTurns * 2) messages,
      // avoiding Context Window Bloat and reducing DB parsing and LLM token billing costs.
      const sliced = messages.slice(-this.maxTurns * 2);
      return sliced.map((msg: { role: string; content: string }) => ({
        role: msg.role as "user" | "assistant" | "system",
        content:
          msg.role === "assistant"
            ? sanitizeTenantResponse(msg.content, businessId)
            : msg.content,
      }));
    } catch (err) {
      console.error("[ShortMemory Error] Failed to get messages:", err);
      return [];
    }
  }

  async addMessage(
    role: "user" | "assistant" | "system",
    content: string,
  ): Promise<void> {
    const id = crypto.randomUUID
      ? crypto.randomUUID()
      : Math.random().toString(36).substring(2, 15);
    const timestamp = getMonotonicTimestamp();
    const cleanContent =
      content !== undefined && content !== null ? String(content) : "";

    try {
      await db.createThread(
        this.threadId,
        "83d67d4e-104c-4325-8aa7-10d4389fc725",
      );
      await db.addMessage({
        id,
        threadId: this.threadId,
        role,
        content: cleanContent,
        timestamp,
      });
      console.log(
        `[ShortMemory] Added message for thread ${this.threadId}: [${role}] ${cleanContent.substring(0, 50)}`,
      );
    } catch (err) {
      console.error("[ShortMemory Error] Failed to add message:", err);
    }
  }

  async compress(messages: ShortMemoryMessage[]): Promise<string> {
    return "Summary of compressed conversation history";
  }
}
