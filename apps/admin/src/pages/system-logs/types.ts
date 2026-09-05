export interface SystemLogRecord {
  id: string;
  traceId: string;
  businessId: string;
  model: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  latencyMs: number;
  statusCode: number;
  logType: 'llm_call' | 'intent_triage' | 'session_metric' | 'tool_execution' | 'system_error';
  rawDetail: Record<string, any>;
  timestamp: string;
}
