import { Injectable } from '@nestjs/common';
import { TenantRegistryService } from 'business-configs';
import { getPgPool } from 'db';

export interface TenantListItem {
  id: string;
  name: string;
  industry?: string;
  channel?: string;
  apiKey?: string;
  refundLimit?: number;
  autoEscalation?: boolean;
  webhookUrl?: string;
  status: string;
  createdAt?: string;
}

@Injectable()
export class TenantService {
  async getTenantConfig(tenantId: string) {
    return TenantRegistryService.getTenantConfig(tenantId);
  }

  async getAvailableTenants(): Promise<TenantListItem[]> {
    try {
      const pool = getPgPool();
      const res = await pool.query(`
        SELECT
          t.id AS tenant_uuid,
          t.business_id,
          t.name,
          t.status,
          t.created_at,
          tc.spi_config,
          tc.skills_config
        FROM tenants t
        LEFT JOIN tenant_configs tc ON LOWER(t.business_id) = LOWER(tc.business_id)
        ORDER BY t.created_at DESC
      `);

      if (res.rows && res.rows.length > 0) {
        return res.rows.map((row) => {
          const spi = row.spi_config && typeof row.spi_config === 'object' ? row.spi_config : {};
          return {
            id: row.business_id,
            name: row.name,
            industry: '综合零售',
            channel: 'Web + Mobile + SPI',
            apiKey: spi.apiSecret || `key_${row.business_id}_sec`,
            refundLimit: 300,
            autoEscalation: true,
            webhookUrl: spi.spiBaseUrl || 'http://localhost:3005',
            status: row.status || 'active',
            createdAt: row.created_at ? new Date(row.created_at).toISOString().split('T')[0] : '2026-01-01',
          };
        });
      }
    } catch (err) {
      console.warn('[TenantService] Failed to query PostgreSQL tenants table:', err);
    }

    return [
      {
        id: 'nike',
        name: 'Nike 官方旗舰店',
        industry: '运动服饰',
        channel: 'Web + Mobile + WeChat',
        apiKey: 'key_nike_sec_9942a',
        refundLimit: 500,
        autoEscalation: true,
        webhookUrl: 'https://api.nike.com/webhooks/agent',
        status: 'active',
        createdAt: '2026-01-10',
      },
      {
        id: 'adidas',
        name: 'Adidas 运动专营',
        industry: '运动鞋履',
        channel: 'Web Widget',
        apiKey: 'key_adi_sec_8112b',
        refundLimit: 300,
        autoEscalation: true,
        webhookUrl: 'https://spi.adidas.com/v1/approvals',
        status: 'active',
        createdAt: '2026-02-01',
      },
      {
        id: 'ecommerce',
        name: '通用电商主站 (Default)',
        industry: '综合零售',
        channel: 'All Open Channels',
        apiKey: 'key_ecom_sec_1001x',
        refundLimit: 200,
        autoEscalation: false,
        webhookUrl: 'https://internal.ecommerce.com/spi',
        status: 'active',
        createdAt: '2025-11-20',
      },
    ];
  }

  async createTenant(data: {
    id: string;
    name: string;
    industry?: string;
    channel?: string;
    apiKey?: string;
    refundLimit?: number;
    webhookUrl?: string;
    status?: string;
  }) {
    const cleanId = (data.id || '').toLowerCase().trim();
    if (!cleanId || !data.name) {
      throw new Error('Tenant ID and Name are required');
    }

    const pool = getPgPool();

    await pool.query(
      `INSERT INTO tenants (business_id, name, plan_tier, status)
       VALUES ($1, $2, 'enterprise', $3)
       ON CONFLICT (business_id) DO UPDATE SET
         name = EXCLUDED.name,
         status = EXCLUDED.status`,
      [cleanId, data.name, data.status || 'active'],
    );

    const spiConfig = {
      mode: 'remote_spi',
      spiBaseUrl: data.webhookUrl || 'http://localhost:3005',
      apiSecret: data.apiKey || `key_${cleanId}_sec`,
      timeoutMs: 5000,
    };

    const skillsConfig = {
      skill_order_refund: {
        enabled: true,
        approvalThresholdAmount: data.refundLimit ?? 300,
      },
    };

    const existingConfig = await pool.query('SELECT id FROM tenant_configs WHERE LOWER(business_id) = $1 LIMIT 1', [
      cleanId,
    ]);

    if (existingConfig.rows && existingConfig.rows.length > 0) {
      await pool.query(
        `UPDATE tenant_configs
         SET spi_config = $1, skills_config = $2, updated_at = NOW()
         WHERE id = $3`,
        [JSON.stringify(spiConfig), JSON.stringify(skillsConfig), existingConfig.rows[0].id],
      );
    } else {
      await pool.query(
        `INSERT INTO tenant_configs (business_id, system_prompt, welcome_message, status, version, spi_config, enabled_skills, skills_config)
         VALUES ($1, $2, $3, 'published', 1, $4, $5, $6)`,
        [
          cleanId,
          `You are the official AI Customer Support Agent for ${data.name}.`,
          `您好！欢迎来到 ${data.name}，请问有什么可以帮您？`,
          JSON.stringify(spiConfig),
          JSON.stringify(['skill_order_address_modification', 'skill_order_refund', 'skill_product_inquiry']),
          JSON.stringify(skillsConfig),
        ],
      );
    }

    TenantRegistryService.invalidateCache(cleanId);
    return { success: true, businessId: cleanId };
  }

  async deleteTenant(businessId: string) {
    const cleanId = businessId.toLowerCase().trim();
    const pool = getPgPool();
    await pool.query('DELETE FROM tenant_configs WHERE LOWER(business_id) = $1', [cleanId]);
    await pool.query('DELETE FROM tenants WHERE LOWER(business_id) = $1', [cleanId]);
    TenantRegistryService.invalidateCache(cleanId);
    return { success: true };
  }
}
