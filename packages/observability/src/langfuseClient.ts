import type { SpanData, TraceData } from "types";

// Mock Langfuse client for initialization
export const langfuse = {
  trace: (data: TraceData) => ({
    span: (spanData: SpanData) => ({
      end: () => {},
    }),
    end: () => {},
  }),
};
