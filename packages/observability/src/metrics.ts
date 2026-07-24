// Mock metrics implementation
export const metrics = {
  increment: (name: string, tags?: Record<string, string>) => {},
  gauge: (name: string, value: number, tags?: Record<string, string>) => {},
};
