import type { RichCardBlock, SubTask, SubTaskResult, TaskPlan } from 'types';

export type { SubTaskResult, TaskPlan };
export type Subtask = SubTask;

export interface Message {
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  plan?: TaskPlan;
  cards?: RichCardBlock[];
  imageUrls?: string[];
  jobId?: string;
  isLoading?: boolean;
  /** S2a:被用户打断的回复(部分态诚实标注,ChatArea 渲染「已停止生成」标记) */
  interrupted?: boolean;
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
