import type {
  SpiConnectorConfig,
  ThirdPartyOrder,
  ThirdPartyOrderActionRequest,
  ThirdPartyOrderActionResult,
  ThirdPartyProduct,
  ThirdPartyUser,
} from 'types';
import type { ThirdPartySpiClient } from './types';

/**
 * MCP (Model Context Protocol) 远程连接器适配器
 * 支持通过标准 MCP JSON-RPC / SSE 协议连接第三方自建的 MCP Server
 */
export class McpConnectorAdapter implements ThirdPartySpiClient {
  private readonly endpoint: string;
  private readonly customHeaders: Record<string, string>;

  constructor(config: SpiConnectorConfig) {
    if (!config.mcpEndpoint) {
      throw new Error('[McpConnectorAdapter] mcpEndpoint is required for MCP mode.');
    }
    this.endpoint = config.mcpEndpoint;
    this.customHeaders = config.customHeaders || {};
  }

  /**
   * 发送标准 MCP JSON-RPC 2.0 工具调用请求
   */
  private async callMcpTool<T>(toolName: string, args: Record<string, unknown>): Promise<T> {
    const payload = {
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'tools/call',
      params: {
        name: toolName,
        arguments: args,
      },
    };

    const resp = await fetch(this.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.customHeaders,
      },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      throw new Error(`MCP Server Error: HTTP ${resp.status} - ${resp.statusText}`);
    }

    const resJson = (await resp.json()) as {
      result?: { content?: Array<{ type: string; text?: string }> };
      error?: { message: string };
    };

    if (resJson.error) {
      throw new Error(`MCP Tool ${toolName} Error: ${resJson.error.message}`);
    }

    const textContent = resJson.result?.content?.find((c) => c.type === 'text')?.text;
    if (!textContent) {
      return {} as T;
    }

    try {
      return JSON.parse(textContent) as T;
    } catch {
      return textContent as unknown as T;
    }
  }

  public async getUserInfo(params: {
    userId?: string;
    userEmail?: string;
    threadId?: string;
    tenantId: string;
  }): Promise<ThirdPartyUser | null> {
    try {
      return await this.callMcpTool<ThirdPartyUser>('get_user_info', params);
    } catch (err) {
      console.error('[McpConnectorAdapter] getUserInfo failed:', err);
      return null;
    }
  }

  public async listOrders(params: {
    userId?: string;
    userEmail?: string;
    threadId?: string;
    status?: string;
    tenantId: string;
    limit?: number;
  }): Promise<ThirdPartyOrder[]> {
    try {
      const res = await this.callMcpTool<ThirdPartyOrder[]>('list_orders', params);
      return Array.isArray(res) ? res : [];
    } catch (err) {
      console.error('[McpConnectorAdapter] listOrders failed:', err);
      return [];
    }
  }

  public async getOrderDetail(params: {
    orderId: string;
    tenantId: string;
  }): Promise<ThirdPartyOrder | null> {
    try {
      return await this.callMcpTool<ThirdPartyOrder>('get_order_detail', params);
    } catch (err) {
      console.error('[McpConnectorAdapter] getOrderDetail failed:', err);
      return null;
    }
  }

  public async executeOrderAction(
    req: ThirdPartyOrderActionRequest & { tenantId: string },
  ): Promise<ThirdPartyOrderActionResult> {
    return await this.callMcpTool<ThirdPartyOrderActionResult>(
      'execute_order_action',
      req as unknown as Record<string, unknown>,
    );
  }

  public async searchProducts(params: {
    query: string;
    category?: string;
    tenantId: string;
    limit?: number;
  }): Promise<ThirdPartyProduct[]> {
    try {
      const res = await this.callMcpTool<ThirdPartyProduct[]>('search_products', params);
      return Array.isArray(res) ? res : [];
    } catch (err) {
      console.error('[McpConnectorAdapter] searchProducts failed:', err);
      return [];
    }
  }
}
