import { getPgPool } from 'db';
import type { BusinessConfig, SpiConnectorConfig } from 'types';

export class TenantRegistryService {
  private static readonly cache = new Map<string, { config: BusinessConfig; timestamp: number }>();
  private static readonly TTL_MS = 60 * 1000; // 1 分钟缓存

  /**
   * 从数据库物理表动态获取入驻商户的配置与元数据 (Zero Hardcode)
   */
  public static async getTenantConfig(businessId = 'ecommerce'): Promise<BusinessConfig> {
    const cleanId = businessId.toLowerCase().trim();
    const now = Date.now();
    const cached = TenantRegistryService.cache.get(cleanId);
    if (cached && now - cached.timestamp < TenantRegistryService.TTL_MS) {
      return cached.config;
    }

    const pool = getPgPool();
    let displayName = `${cleanId.charAt(0).toUpperCase() + cleanId.slice(1)} 官方旗舰店`;
    let systemPrompt = `You are a professional AI Customer Support Agent for ${displayName}. Help customers with order tracking, address modification, refunds, and product inquiries.`;
    let spiConnector: SpiConnectorConfig = { mode: 'local_db' };
    let enabledSkills: string[] = ['skill_order_address_modification', 'skill_order_refund', 'skill_product_inquiry'];

    try {
      // 1. 查询 tenants 表获取商户动态入驻名称
      const tenantRes = await pool.query('SELECT name, status FROM tenants WHERE LOWER(business_id) = $1 LIMIT 1', [
        cleanId,
      ]);

      if (tenantRes.rows?.[0]) {
        displayName = tenantRes.rows[0].name || displayName;
      }

      // 2. 查询 tenant_configs 表获取动态配置、SPI 连接器与启用的技能
      const configRes = await pool.query(
        'SELECT system_prompt, spi_config, enabled_skills FROM tenant_configs WHERE LOWER(business_id) = $1 ORDER BY version DESC LIMIT 1',
        [cleanId],
      );

      if (configRes.rows?.[0]) {
        const row = configRes.rows[0];
        if (row.system_prompt) systemPrompt = row.system_prompt;
        if (row.spi_config) {
          spiConnector = row.spi_config as SpiConnectorConfig;
          if (process.env.SPI_BASE_URL_OVERRIDE) {
            spiConnector = {
              ...spiConnector,
              spiBaseUrl: process.env.SPI_BASE_URL_OVERRIDE,
            };
          }
        }
        if (Array.isArray(row.enabled_skills)) enabledSkills = row.enabled_skills;
      }
    } catch (err) {
      console.warn(`[TenantRegistryService] Failed to load tenant config for ${cleanId} from DB:`, err);
    }

    const result: BusinessConfig = {
      businessId: cleanId,
      name: displayName,
      systemPrompt,
      spiConnector,
      enabledSkills,
      confidenceThresholds: { high: 0.85, mid: 0.6 },
      refundAutoApprovalLimit: 50,
    };

    TenantRegistryService.cache.set(cleanId, {
      config: result,
      timestamp: now,
    });
    return result;
  }

  /**
   * 动态获取商户展示名称 (完全基于数据库入驻信息)
   */
  public static async getMerchantDisplayName(businessId = 'ecommerce'): Promise<string> {
    const config = await TenantRegistryService.getTenantConfig(businessId);
    return config.name || `${businessId} 官方商城`;
  }

  /**
   * 清除缓存
   */
  public static invalidateCache(businessId?: string): void {
    if (businessId) {
      TenantRegistryService.cache.delete(businessId.toLowerCase().trim());
    } else {
      TenantRegistryService.cache.clear();
    }
  }
}
