import type { z } from 'zod';

export interface ToolDefinition {
  name: string;
  description: string;
  schema: z.ZodObject<any>;
  execute: (args: any) => Promise<any>;
}

const registry = new Map<string, ToolDefinition>();

export function registerTool(tool: ToolDefinition) {
  registry.set(tool.name, tool);
}

export function getTool(name: string): ToolDefinition | undefined {
  return registry.get(name);
}

export function getAllTools(): ToolDefinition[] {
  return Array.from(registry.values());
}
