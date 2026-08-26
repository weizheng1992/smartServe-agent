import crypto from 'node:crypto';
import type {
  SpiConnectorConfig,
  SpiResponse,
  ThirdPartyOrder,
  ThirdPartyOrderActionRequest,
  ThirdPartyOrderActionResult,
  ThirdPartyProduct,
  ThirdPartyUser,
} from 'types';
import { isSafeUrl } from '../openapi/ssrfGuard';
import { HmacSigner } from './hmacSigner';
import type { ThirdPartySpiClient } from './types';

/**
 * 远程标准 HTTP SPI 连接器 (Remote HTTP SPI Adapter)
 * 用于连接第三方独立电商系统、Shopify 中继网关或自研 OMS/ERP 系统
 */
export class RemoteHttpSpiAdapter implements ThirdPartySpiClient {
  private readonly baseUrl: string;
  private readonly apiSecret?: string;
  private readonly timeoutMs: number;
  private readonly customHeaders: Record<string, string>;
  private readonly enableHmacSign: boolean;

  constructor(config: SpiConnectorConfig) {
    const rawUrl = process.env.SPI_BASE_URL_OVERRIDE || config.spiBaseUrl;
    if (!rawUrl) {
      throw new Error('[RemoteHttpSpiAdapter] spiBaseUrl is required for remote SPI mode.');
    }
    this.baseUrl = (config.spiBaseUrl || rawUrl).replace(/\/+$/, '');
    this.apiSecret = config.apiSecret;
    this.timeoutMs = config.timeoutMs || 8000;
    this.customHeaders = config.customHeaders || {};
    this.enableHmacSign = config.enableHmacSign ?? Boolean(config.apiSecret);
  }

  private getEffectiveBaseUrl(): string {
    const override = process.env.SPI_BASE_URL_OVERRIDE;
    if (override) {
      return override.replace(/\/+$/, '');
    }
    return this.baseUrl;
  }

  private async request<T>(
    method: 'GET' | 'POST' | 'PUT' | 'DELETE',
    path: string,
    query?: Record<string, string | number | undefined>,
    body?: unknown,
    idempotencyKey?: string,
    tenantId = 'ecommerce',
  ): Promise<T> {
    const effectiveBaseUrl = this.getEffectiveBaseUrl();
    const urlObj = new URL(`${effectiveBaseUrl}${path}`);
    if (query) {
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined && v !== null) {
          urlObj.searchParams.set(k, String(v));
        }
      }
    }

    const fullUrl = urlObj.toString();
    const isDev = process.env.NODE_ENV !== 'production';
    const isLocalhost = urlObj.hostname === 'localhost' || urlObj.hostname === '127.0.0.1';

    if (!isDev || !isLocalhost) {
      const check = await isSafeUrl(fullUrl);
      if (!check.safe) {
        throw new Error(`[RemoteHttpSpiAdapter] SSRF Blocked: Target URL ${fullUrl} is not permitted.`);
      }
    }

    const timestamp = Date.now();
    const nonce = crypto.randomUUID();
    const bodyStr = body ? JSON.stringify(body) : '';

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Tenant-Id': tenantId,
      'X-Timestamp': timestamp.toString(),
      'X-Nonce': nonce,
      ...this.customHeaders,
    };

    if (idempotencyKey) {
      headers['X-Idempotency-Key'] = idempotencyKey;
    }

    if (this.enableHmacSign && this.apiSecret) {
      const signature = HmacSigner.sign({
        method,
        path: urlObj.pathname,
        timestamp,
        nonce,
        body: bodyStr,
        secret: this.apiSecret,
      });
      headers['X-Signature'] = signature;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const resp = await fetch(fullUrl, {
        method,
        headers,
        body: bodyStr || undefined,
        signal: controller.signal,
      });

      if (!resp.ok) {
        const errorText = await resp.text().catch(() => '');
        throw new Error(`HTTP ${resp.status} - ${errorText || resp.statusText}`);
      }

      const json = (await resp.json()) as SpiResponse<T>;
      if (json && typeof json === 'object' && 'success' in json && !json.success) {
        throw new Error(json.message || 'Third-party SPI returned unsuccessful response');
      }

      return (json && 'data' in json ? json.data : json) as T;
    } finally {
      clearTimeout(timer);
    }
  }

  public async getUserInfo(params: {
    userId?: string;
    userEmail?: string;
    threadId?: string;
    tenantId: string;
  }): Promise<ThirdPartyUser | null> {
    try {
      return await this.request<ThirdPartyUser>(
        'GET',
        '/spi/v1/user/info',
        {
          userId: params.userId,
          userEmail: params.userEmail,
          threadId: params.threadId,
        },
        undefined,
        undefined,
        params.tenantId,
      );
    } catch (err) {
      console.error('[RemoteHttpSpiAdapter] getUserInfo failed:', err);
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
      const res = await this.request<ThirdPartyOrder[]>(
        'GET',
        '/spi/v1/orders/list',
        {
          userId: params.userId,
          userEmail: params.userEmail,
          threadId: params.threadId,
          status: params.status,
          limit: params.limit,
        },
        undefined,
        undefined,
        params.tenantId,
      );
      return Array.isArray(res) ? res : [];
    } catch (err) {
      console.error('[RemoteHttpSpiAdapter] listOrders failed:', err);
      return [];
    }
  }

  public async getOrderDetail(params: {
    orderId: string;
    tenantId: string;
  }): Promise<ThirdPartyOrder | null> {
    try {
      return await this.request<ThirdPartyOrder>(
        'GET',
        '/spi/v1/orders/detail',
        { orderId: params.orderId },
        undefined,
        undefined,
        params.tenantId,
      );
    } catch (err) {
      console.error('[RemoteHttpSpiAdapter] getOrderDetail failed:', err);
      return null;
    }
  }

  public async executeOrderAction(
    req: ThirdPartyOrderActionRequest & { tenantId: string },
  ): Promise<ThirdPartyOrderActionResult> {
    return await this.request<ThirdPartyOrderActionResult>(
      'POST',
      '/spi/v1/orders/action',
      undefined,
      req,
      req.idempotencyKey,
      req.tenantId,
    );
  }

  public async searchProducts(params: {
    query: string;
    category?: string;
    tenantId: string;
    limit?: number;
  }): Promise<ThirdPartyProduct[]> {
    try {
      const res = await this.request<ThirdPartyProduct[]>(
        'GET',
        '/spi/v1/products/search',
        { query: params.query, category: params.category, limit: params.limit },
        undefined,
        undefined,
        params.tenantId,
      );
      return Array.isArray(res) ? res : [];
    } catch (err) {
      console.error('[RemoteHttpSpiAdapter] searchProducts failed:', err);
      return [];
    }
  }
}
