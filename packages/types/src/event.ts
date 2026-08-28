export interface AgentEvent {
  event: string;
  data: unknown;
  jobId?: string;
  timestamp?: number;
  [key: string]: unknown;
}

export interface CardStreamEventPayload {
  cardId: string;
  type: string;
  hydrationState: 'skeleton' | 'hydrating' | 'ready' | 'action_pending' | 'settled';
  data?: unknown;
  patch?: Record<string, unknown>;
}

export interface RunningDetail {
  id?: string;
  node?: string;
  message?: string;
  desc?: string;
  resultText?: string;
  timestamp?: string;
  status?: 'running' | 'completed' | 'failed' | string;
  output?: unknown;
  [key: string]: unknown;
}

export type SSECallback = (data: unknown) => void;
