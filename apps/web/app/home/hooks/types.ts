import type { SubTask, SubTaskResult, TaskPlan } from "types";

export type { SubTaskResult, TaskPlan };
export type Subtask = SubTask;

export interface Message {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  plan?: TaskPlan;
  jobId?: string;
  isLoading?: boolean;
  timestamp?: string;
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
