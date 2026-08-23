import type { SpiConnectorConfig } from 'types';
import { LocalDbSpiAdapter } from './localDbSpiAdapter';
import { McpConnectorAdapter } from './mcpConnectorAdapter';
import { RemoteHttpSpiAdapter } from './remoteHttpSpiAdapter';
import type { ThirdPartySpiClient } from './types';

export class SpiConnectorFactory {
  private static readonly adapterCache = new Map<string, ThirdPartySpiClient>();
  private static readonly localAdapter = new LocalDbSpiAdapter();

  /**
   * 根据租户接入配置创建或获取对应的 SPI 客户端
   */
  public static getClient(config?: SpiConnectorConfig, tenantId = 'ecommerce'): ThirdPartySpiClient {
    if (!config || config.mode === 'local_db') {
      return SpiConnectorFactory.localAdapter;
    }

    const cacheKey = `${tenantId}:${config.mode}:${config.spiBaseUrl || config.mcpEndpoint || 'default'}`;
    const cached = SpiConnectorFactory.adapterCache.get(cacheKey);
    if (cached) {
      return cached;
    }

    let client: ThirdPartySpiClient;
    switch (config.mode) {
      case 'remote_spi':
        client = new RemoteHttpSpiAdapter(config);
        break;
      case 'mcp_server':
        client = new McpConnectorAdapter(config);
        break;
      default:
        client = SpiConnectorFactory.localAdapter;
        break;
    }

    SpiConnectorFactory.adapterCache.set(cacheKey, client);
    return client;
  }

  /**
   * 清除特定租户的连接器缓存
   */
  public static invalidateCache(tenantId?: string): void {
    if (!tenantId) {
      SpiConnectorFactory.adapterCache.clear();
      return;
    }
    Array.from(SpiConnectorFactory.adapterCache.keys()).forEach((key) => {
      if (key.startsWith(`${tenantId}:`)) {
        SpiConnectorFactory.adapterCache.delete(key);
      }
    });
  }
}
