import type { z } from 'zod';
import { scrubPii } from './scrubber';

export interface ToolDefinition<TArgs = any, TResult = any> {
  name: string;
  description: string;
  schema: z.ZodObject<z.ZodRawShape>;
  execute: (args: TArgs) => Promise<TResult>;
}

const registry = new Map<string, ToolDefinition<any, any>>();

export function registerTool(tool: ToolDefinition<any, any>) {
  // Wrap tool execution with PII scrubbing layer for safe logging/tracing
  const originalExecute = tool.execute;
  const wrappedTool: ToolDefinition<any, any> = {
    ...tool,
    execute: async (args: any) => {
      const scrubbedArgs = scrubPii(args);
      const result = await originalExecute(scrubbedArgs);
      return scrubPii(result);
    },
  };
  registry.set(tool.name, wrappedTool);
}

export function getTool(name: string): ToolDefinition<any, any> | undefined {
  return registry.get(name);
}

export function getAllTools(): ToolDefinition<any, any>[] {
  return Array.from(registry.values());
}
