import { decryptSecret, redactSensitiveObject } from '../crypto/secrets';
import { scrubPii } from '../scrubber';
import { isSafeUrl } from './ssrfGuard';

export interface DynamicHttpToolConfig {
  name: string;
  description: string;
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  url: string;
  headers?: Record<string, string>;
  schema?: Record<string, unknown>;
  authType?: 'none' | 'bearer' | 'basic' | 'custom_header';
  encryptedCredentials?: string | null;
  tenantId?: string;
  masterKey?: string;
  requiresApproval?: boolean;
}

export interface DynamicToolExecutionResult {
  success: boolean;
  data?: unknown;
  error?: string;
  statusCode?: number;
}

export interface DynamicHttpTool {
  name: string;
  description: string;
  schema?: Record<string, unknown>;
  requiresApproval: boolean;
  execute: (args: Record<string, unknown>) => Promise<DynamicToolExecutionResult>;
}

export function createDynamicHttpTool(config: DynamicHttpToolConfig): DynamicHttpTool {
  const {
    name,
    description,
    method = 'GET',
    url,
    headers = {},
    schema,
    authType = 'none',
    encryptedCredentials,
    tenantId = 'default_tenant',
    masterKey,
    requiresApproval = false,
  } = config;

  return {
    name,
    description,
    schema,
    requiresApproval,
    execute: async (args: Record<string, unknown>): Promise<DynamicToolExecutionResult> => {
      // 1. 🛡️ SSRF 防御检测
      const safetyCheck = await isSafeUrl(url);
      if (!safetyCheck.safe) {
        return {
          success: false,
          error: `[SSRF Blocked] Request to ${url} was blocked for safety reasons: ${safetyCheck.reason}`,
        };
      }

      // 2. 🔑 动态装配 Headers 与 JIT 即时解密
      const requestHeaders: Record<string, string> = {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...headers,
      };

      if (encryptedCredentials && authType !== 'none') {
        try {
          const decrypted = decryptSecret(encryptedCredentials, masterKey, tenantId);
          if (authType === 'bearer') {
            requestHeaders.Authorization = `Bearer ${decrypted.trim()}`;
          } else if (authType === 'basic') {
            requestHeaders.Authorization = `Basic ${decrypted.trim()}`;
          } else if (authType === 'custom_header') {
            requestHeaders['X-API-Key'] = decrypted.trim();
          }
        } catch (decryptErr) {
          return {
            success: false,
            error: `Failed to decrypt tenant credentials for tool ${name}: ${decryptErr instanceof Error ? decryptErr.message : String(decryptErr)}`,
          };
        }
      }

      // 3. 🌐 组装请求并设置 8 秒物理超时熔断
      try {
        let requestUrl = url;
        const fetchOptions: RequestInit = {
          method,
          headers: requestHeaders,
          signal: AbortSignal.timeout(8000), // 8s timeout
        };

        if (method === 'GET') {
          const urlObj = new URL(url);
          for (const [k, v] of Object.entries(args)) {
            if (v !== undefined && v !== null) {
              urlObj.searchParams.set(k, String(v));
            }
          }
          requestUrl = urlObj.toString();
        } else {
          fetchOptions.body = JSON.stringify(args);
        }

        const response = await fetch(requestUrl, fetchOptions);
        const text = await response.text();

        let parsedData: unknown;
        try {
          parsedData = JSON.parse(text);
        } catch {
          parsedData = text;
        }

        // 4. 🧹 PII 敏感信息脱敏与凭据清洗
        const scrubbedData = scrubPii(redactSensitiveObject(parsedData));

        if (!response.ok) {
          return {
            success: false,
            statusCode: response.status,
            error: `Remote server responded with HTTP ${response.status}`,
            data: scrubbedData,
          };
        }

        return {
          success: true,
          statusCode: response.status,
          data: scrubbedData,
        };
      } catch (err: unknown) {
        const errMsg = err instanceof Error ? err.message : String(err);
        return {
          success: false,
          error: `HTTP Tool Execution Failed: ${errMsg}`,
        };
      }
    },
  };
}
