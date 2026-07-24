export interface SubTask {
  id: string;
  description: string;
  status: 'pending' | 'executing' | 'completed' | 'failed';
  result?: any;
}

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
    return null;
  }

  async saveTaskState(state: TaskState): Promise<void> {
    console.log(`[TaskMemory] Saving state for thread ${this.threadId}: ${JSON.stringify(state)}`);
  }
}
