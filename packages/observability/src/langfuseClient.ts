// Mock Langfuse client for initialization
export const langfuse = {
  trace: (data: any) => ({
    span: (spanData: any) => ({
      end: () => {},
    }),
    end: () => {},
  }),
};
