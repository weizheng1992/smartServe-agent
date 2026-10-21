import type { RichCardBlock } from 'types';

export interface StreamStatusEvent {
  node?: string;
  nodeName?: string;
  message?: string;
  tokens?: number;
  plan?: unknown;
}

export interface StreamResultEvent {
  output?: string;
  taskPlan?: unknown;
  cards?: RichCardBlock[];
  tokens?: number;
  /** S2a:用户打断的终局帧(引擎 S2c 收口)—— true 时部分态诚实标注,严禁假装修完 */
  interrupted?: boolean;
  /** 配额拒机读码(2026-10-21 配额闸,增量键;仅拒时出现,output 为后端权威文案) */
  quotaCode?: string;
}

export interface AgentStreamClientCallbacks {
  onStatus?: (event: StreamStatusEvent) => void;
  onResult?: (event: StreamResultEvent) => void;
  onError?: (error: unknown) => void;
}

export class AgentStreamClient {
  private eventSource: EventSource | null = null;
  private jobId: string;

  constructor(jobId: string) {
    this.jobId = jobId;
  }

  /**
   * 🎧 建立与 Agent 执行流的 SSE 长连接 (Establish SSE Stream Connection)
   */
  public connect(callbacks: AgentStreamClientCallbacks): () => void {
    if (typeof EventSource === 'undefined') {
      callbacks.onError?.(new Error('EventSource is not supported in this environment'));
      return () => {};
    }

    try {
      this.eventSource = new EventSource(`/api/chat/${this.jobId}/stream`);

      this.eventSource.addEventListener('status', (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          let nodeName = data.node || 'system';

          if (data.node === 'triage') {
            nodeName = 'Triage 节点';
          } else if (data.node === 'planner') {
            nodeName = 'Planner 节点';
          } else if (data.node === 'executor') {
            nodeName = 'Executor 节点';
          } else if (data.node === 'validator') {
            nodeName = 'Validator 节点';
          }

          callbacks.onStatus?.({
            ...data,
            nodeName,
          });
        } catch (err) {
          console.warn('[AgentStreamClient] Failed to parse status event JSON:', err);
        }
      });

      this.eventSource.addEventListener('result', (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          this.close();
          callbacks.onResult?.(data);
        } catch (err) {
          console.warn('[AgentStreamClient] Failed to parse result event JSON:', err);
          this.close();
          callbacks.onError?.(err);
        }
      });

      this.eventSource.addEventListener('error', (event: Event) => {
        console.error('[AgentStreamClient] SSE Stream error encountered:', event);
        this.close();
        callbacks.onError?.(event);
      });
    } catch (err) {
      this.close();
      callbacks.onError?.(err);
    }

    return () => this.close();
  }

  /**
   * 🔒 物理断开并释放 SSE 资源 (Close & Dispose Connection)
   */
  public close(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}
