import type { SubTaskResult } from "types";

export interface Subtask {
  id: string;
  description: string;
  status: "pending" | "executing" | "completed" | "failed";
  result?: SubTaskResult;
}

export interface TaskPlan {
  goal: string;
  subtasks: Subtask[];
  currentStepIndex: number;
}

export interface Message {
  role: "user" | "assistant";
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
