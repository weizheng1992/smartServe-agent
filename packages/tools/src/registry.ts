import type { z } from "zod";
import { scrubPii } from "./scrubber";

export interface ToolDefinition<
  TArgs = Record<string, unknown>,
  TResult = unknown,
> {
  name: string;
  description: string;
  schema: z.ZodObject<z.ZodRawShape>;
  execute: (args: TArgs) => Promise<TResult>;
}

const registry = new Map<string, ToolDefinition>();

export function registerTool(tool: ToolDefinition) {
  // Wrap tool execution with PII scrubbing layer for safe logging/tracing
  const originalExecute = tool.execute;
  const wrappedTool: ToolDefinition = {
    ...tool,
    execute: async (args: any) => {
      const scrubbedArgs = scrubPii(args);
      const result = await originalExecute(scrubbedArgs);
      return scrubPii(result);
    },
  };
  registry.set(tool.name, wrappedTool);
}

export function getTool(name: string): ToolDefinition | undefined {
  return registry.get(name);
}

export function getAllTools(): ToolDefinition[] {
  return Array.from(registry.values());
}
