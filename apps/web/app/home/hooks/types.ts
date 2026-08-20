import type { SubTask, SubTaskResult, TaskPlan } from 'types';

export type { SubTaskResult, TaskPlan };
export type Subtask = SubTask;

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  plan?: TaskPlan;
  jobId?: string;
  isLoading?: boolean;
}

export interface UserSession {
  id: string;
  email: string;
}

export interface ChatThread {
  id: string;
  userId: string;
  businessId: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}
