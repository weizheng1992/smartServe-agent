export interface SpanData {
  name: string;
  input?: unknown;
  output?: unknown;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface TraceData {
  id?: string;
  name: string;
  userId?: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SpanClient {
  end?: (output?: unknown) => void;
  event?: (name: string, data?: unknown) => void;
  [key: string]: unknown;
}

export interface TraceClient {
  span: (spanData: SpanData) => SpanClient;
  end?: (output?: unknown) => void;
  [key: string]: unknown;
}
