import { taskMemory as dbTaskMemory, getDrizzle } from 'db';
import type { SubTask } from 'types';

export type { SubTask };

export interface TaskState {
  goal: string;
  subtasks: SubTask[];
  currentStepIndex: number;
}

export class TaskMemory {
  private threadId: string;

  constructor(threadId: string) {
    this.threadId = threadId;
  }

  async getTaskState(): Promise<TaskState | null> {
    const dbInstance = getDrizzle();
    if (dbInstance) {
      try {
        const { eq } = require('drizzle-orm');
        const rows = await dbInstance
          .select()
          .from(dbTaskMemory)
          .where(eq(dbTaskMemory.threadId, this.threadId))
          .limit(1);
        if (rows && rows.length > 0) {
          const record = rows[0];
          return record.pendingIntents as TaskState;
        }
      } catch (err) {
        console.warn('[TaskMemory] Failed to get task state from DB:', err);
      }
    }
    return null;
  }

  async saveTaskState(state: TaskState): Promise<void> {
    console.log(`[TaskMemory] Saving state for thread ${this.threadId}: ${JSON.stringify(state)}`);
    const dbInstance = getDrizzle();
    if (dbInstance) {
      try {
        const { eq } = require('drizzle-orm');
        // Check if there is an existing record
        const rows = await dbInstance
          .select()
          .from(dbTaskMemory)
          .where(eq(dbTaskMemory.threadId, this.threadId))
          .limit(1);

        if (rows && rows.length > 0) {
          // Update existing task state
          await dbInstance
            .update(dbTaskMemory)
            .set({
              pendingIntents: state,
              updatedAt: new Date(),
            })
            .where(eq(dbTaskMemory.threadId, this.threadId));
        } else {
          // Insert new task state
          await dbInstance.insert(dbTaskMemory).values({
            threadId: this.threadId,
            pendingIntents: state,
            updatedAt: new Date(),
          });
        }
        console.log(`[TaskMemory] Successfully persisted state to DB for thread ${this.threadId}`);
      } catch (err) {
        console.warn('[TaskMemory] Failed to save task state to DB:', err);
      }
    }
  }
}
