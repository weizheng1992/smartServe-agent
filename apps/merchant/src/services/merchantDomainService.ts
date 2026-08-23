import crypto from 'node:crypto';
import type {
  ThirdPartyOrder,
  ThirdPartyOrderActionRequest,
  ThirdPartyOrderActionResult,
  ThirdPartyProduct,
  ThirdPartySku,
  ThirdPartyUser,
} from 'types';
import { ensureMerchantDatabaseAndTables, getMerchantPgPool } from '../db/merchantDb';

export class MerchantDomainService {
  public static readonly MERCHANT_ID = 'aurora';
  public static readonly API_SECRET = 'aurora_secret_key_8899';

  /**
   * 确保数据库与表结构就绪
   */
  private static async ensureDb() {
    await ensureMerchantDatabaseAndTables();
    return getMerchantPgPool();
  }

  /**
   * 1. 获取商户顾客画像与地址簿
   */
  public static async getUserInfo(params: {
    userId?: string;
    userEmail?: string;
  }): Promise<ThirdPartyUser | null> {
    const pool = await this.ensureDb();
    let query = 'SELECT * FROM merchant_customers WHERE 1=1';
    const values: (string | number)[] = [];

    if (params.userId) {
      values.push(params.userId);
      query += ` AND (customer_id = $${values.length} OR customer_id = 'CUST-8801')`;
    } else if (params.userEmail) {
      values.push(params.userEmail);
      query += ` AND email = $${values.length}`;
    }

    query += ' LIMIT 1';

    const res = await pool.query(query, values);
    if (!res.rows?.[0]) {
      // 默认回退主测试顾客
      const fallback = await pool.query('SELECT * FROM merchant_customers WHERE customer_id = $1 LIMIT 1', [
        'CUST-8801',
      ]);
      if (fallback.rows?.[0]) {
        const row = fallback.rows[0];
        return {
          userId: row.customer_id,
          name: row.name,
          phone: row.phone,
          email: row.email,
          memberLevel: row.member_level,
          addresses: (row.addresses || []) as any,
          tags: (row.tags || []) as string[],
        };
      }
      return null;
    }

    const row = res.rows[0];
    return {
      userId: row.customer_id,
      name: row.name,
      phone: row.phone,
      email: row.email,
      memberLevel: row.member_level,
      addresses: (row.addresses || []) as any,
      tags: (row.tags || []) as string[],
    };
  }

  /**
   * 2. 查询指定顾客在商户系统的订单列表
   */
  public static async listOrders(params: {
    userId?: string;
    status?: string;
    limit?: number;
  }): Promise<ThirdPartyOrder[]> {
    const pool = await this.ensureDb();
    const custId = params.userId || 'CUST-8801';

    let sql = 'SELECT * FROM merchant_orders WHERE (customer_id = $1 OR customer_id = $2)';
    const values: (string | number)[] = [custId, 'CUST-8801'];

    if (params.status) {
      values.push(params.status.toUpperCase());
      sql += ` AND status = $${values.length}`;
    }

    sql += ` ORDER BY created_at DESC LIMIT $${values.length + 1}`;
    values.push(params.limit || 10);

    const ordersRes = await pool.query(sql, values);
    const results: ThirdPartyOrder[] = [];

    for (const row of ordersRes.rows) {
      const itemsRes = await pool.query('SELECT * FROM merchant_order_items WHERE order_id = $1', [row.order_id]);

      results.push({
        orderId: row.order_id,
        userId: row.customer_id,
        status: row.status as ThirdPartyOrder['status'],
        totalAmount: row.total_amount,
        currency: row.currency || 'CNY',
        createdAt: row.created_at ? new Date(row.created_at).toISOString() : new Date().toISOString(),
        shippingAddress: row.shipping_address,
        tracking: row.tracking_info,
        isAddressModifiable: Boolean(row.is_address_modifiable),
        isReturnable: Boolean(row.is_returnable),
        items: itemsRes.rows.map((item) => ({
          skuId: item.sku_code,
          productId: item.spu_id || item.sku_code,
          title: item.title,
          quantity: item.quantity,
          price: item.price,
          imageUrl: item.image_url,
          specSummary: item.spec_summary,
        })),
      });
    }

    return results;
  }

  /**
   * 3. 查询单笔订单明细
   */
  public static async getOrderDetail(orderId: string): Promise<ThirdPartyOrder | null> {
    const pool = await this.ensureDb();
    const orderRes = await pool.query('SELECT * FROM merchant_orders WHERE order_id = $1 LIMIT 1', [orderId]);

    if (!orderRes.rows?.[0]) return null;
    const row = orderRes.rows[0];

    const itemsRes = await pool.query('SELECT * FROM merchant_order_items WHERE order_id = $1', [row.order_id]);

    return {
      orderId: row.order_id,
      userId: row.customer_id,
      status: row.status as ThirdPartyOrder['status'],
      totalAmount: row.total_amount,
      currency: row.currency || 'CNY',
      createdAt: row.created_at ? new Date(row.created_at).toISOString() : new Date().toISOString(),
      shippingAddress: row.shipping_address,
      tracking: row.tracking_info,
      isAddressModifiable: Boolean(row.is_address_modifiable),
      isReturnable: Boolean(row.is_returnable),
      items: itemsRes.rows.map((item) => ({
        skuId: item.sku_code,
        productId: item.spu_id || item.sku_code,
        title: item.title,
        quantity: item.quantity,
        price: item.price,
        imageUrl: item.image_url,
        specSummary: item.spec_summary,
      })),
    };
  }

  /**
   * 4. 执行订单履约变更 (改地址 / 退款)
   */
  public static async executeOrderAction(
    req: ThirdPartyOrderActionRequest,
    signature?: string,
  ): Promise<ThirdPartyOrderActionResult> {
    const pool = await this.ensureDb();
    const actionId = `ACT_${Date.now()}_${crypto.randomBytes(4).toString('hex')}`;

    // 幂等防重检查
    if (req.idempotencyKey) {
      const existing = await pool.query('SELECT * FROM merchant_audit_logs WHERE idempotency_key = $1 LIMIT 1', [
        req.idempotencyKey,
      ]);
      if (existing.rows?.[0]) {
        const log = existing.rows[0];
        const result = (typeof log.result === 'string' ? JSON.parse(log.result) : log.result) as Record<
          string,
          unknown
        >;
        return {
          ...result,
          success: true,
          actionType: req.actionType,
          orderId: req.orderId,
          actionId: log.id,
          message: '幂等防重响应：已成功执行过该指令',
        };
      }
    }

    const order = await this.getOrderDetail(req.orderId);
    if (!order) {
      return {
        success: false,
        actionType: req.actionType,
        orderId: req.orderId,
        message: `订单 [${req.orderId}] 不存在`,
      };
    }

    if (req.actionType === 'MODIFY_ADDRESS') {
      if (!order.isAddressModifiable || ['SHIPPED', 'DELIVERED'].includes(order.status)) {
        return {
          success: false,
          actionType: 'MODIFY_ADDRESS',
          orderId: req.orderId,
          message: `修改失败：订单当前状态为【${order.status}】，包裹已发出或完结，禁止修改地址。`,
        };
      }

      const addressStr = typeof req.newAddress === 'string' ? req.newAddress : req.newAddress?.fullAddress || '';

      const updatedAddrObj = {
        recipientName:
          (typeof req.newAddress === 'object' ? req.newAddress?.recipientName : undefined) ||
          order.shippingAddress.recipientName ||
          '客户',
        phone:
          (typeof req.newAddress === 'object' ? req.newAddress?.phone : undefined) ||
          order.shippingAddress.phone ||
          '13800000000',
        fullAddress: addressStr,
      };

      await pool.query('UPDATE merchant_orders SET shipping_address = $1 WHERE order_id = $2', [
        JSON.stringify(updatedAddrObj),
        req.orderId,
      ]);

      const resultPayload = {
        updatedAddress: addressStr,
        message: '收货地址修改成功',
      };

      await pool.query(
        `INSERT INTO merchant_audit_logs (action_type, order_id, idempotency_key, operator, payload, result)
         VALUES ($1, $2, $3, $4, $5, $6)`,
        [
          'MODIFY_ADDRESS',
          req.orderId,
          req.idempotencyKey,
          'AGENT_SPI',
          JSON.stringify({ ...req, signature }),
          JSON.stringify(resultPayload),
        ],
      );

      return {
        success: true,
        actionType: 'MODIFY_ADDRESS',
        orderId: req.orderId,
        actionId,
        ...resultPayload,
      };
    }

    if (req.actionType === 'REQUEST_REFUND') {
      const refundId = `RF_AURORA_${Date.now()}`;
      await pool.query('UPDATE merchant_orders SET status = $1, is_returnable = FALSE WHERE order_id = $2', [
        'REFUNDED',
        req.orderId,
      ]);

      const resultPayload = {
        refundId,
        refundedAmount: req.refundAmount || order.totalAmount,
        message: '极光潮品退款已受理入账',
      };

      await pool.query(
        `INSERT INTO merchant_audit_logs (action_type, order_id, idempotency_key, operator, payload, result)
         VALUES ($1, $2, $3, $4, $5, $6)`,
        [
          'REQUEST_REFUND',
          req.orderId,
          req.idempotencyKey,
          'AGENT_SPI',
          JSON.stringify({ ...req, signature }),
          JSON.stringify(resultPayload),
        ],
      );

      return {
        success: true,
        actionType: 'REQUEST_REFUND',
        orderId: req.orderId,
        actionId,
        ...resultPayload,
      };
    }

    return {
      success: false,
      actionType: req.actionType,
      orderId: req.orderId,
      message: `未知的操作指令: ${req.actionType}`,
    };
  }

  /**
   * 5. 搜索商户现货库存与多规格 SPU / SKU 商品
   */
  public static async searchProducts(
    params: {
      query?: string;
      category?: string;
      limit?: number;
    } = {},
  ): Promise<ThirdPartyProduct[]> {
    const pool = await this.ensureDb();
    let sql = "SELECT * FROM merchant_spus WHERE status = 'ON_SALE'";
    const values: (string | number)[] = [];

    if (params?.query) {
      values.push(`%${params.query}%`);
      sql += ` AND (title ILIKE $${values.length} OR subtitle ILIKE $${values.length} OR category ILIKE $${values.length} OR description ILIKE $${values.length})`;
    }

    if (params?.category) {
      values.push(params.category);
      sql += ` AND category = $${values.length}`;
    }

    sql += ` ORDER BY created_at ASC LIMIT $${values.length + 1}`;
    values.push(params?.limit || 10);

    const spuRes = await pool.query(sql, values);
    const products: ThirdPartyProduct[] = [];

    for (const spu of spuRes.rows) {
      // 关联查询该 SPU 下的所有 SKU 规格
      const skusRes = await pool.query('SELECT * FROM merchant_skus WHERE spu_id = $1 ORDER BY price ASC', [spu.id]);

      const skus: ThirdPartySku[] = skusRes.rows.map((row) => ({
        skuCode: row.sku_code,
        skuTitle: row.sku_title,
        specAttributes: row.spec_attributes,
        price: Number(row.price),
        originalPrice: row.original_price ? Number(row.original_price) : undefined,
        stock: row.stock,
        imageUrl: row.image_url || spu.main_image,
        barCode: row.barcode,
      }));

      const totalStock = skus.reduce((sum, s) => sum + s.stock, 0);
      const minPrice = skus.length > 0 ? Math.min(...skus.map((s) => s.price)) : 0;
      const minOrigPrice =
        skus.length > 0 && skus[0].originalPrice
          ? Math.min(...skus.filter((s) => s.originalPrice).map((s) => s.originalPrice!))
          : undefined;

      products.push({
        productId: spu.spu_code,
        spuId: spu.id,
        title: spu.title,
        subtitle: spu.subtitle,
        description: spu.description,
        price: minPrice,
        originalPrice: minOrigPrice,
        stock: totalStock,
        category: spu.category,
        brand: spu.brand,
        imageUrl: spu.main_image,
        detailImages: spu.banner_images || [],
        specDimensions: spu.spec_dimensions || [],
        skus,
        specs: spu.specs || {},
        isAvailable: totalStock > 0,
      });
    }

    return products;
  }

  /**
   * 6. 前台用户模拟多规格一键下单 (Storefront Spec Selected Purchase)
   */
  public static async placeOrder(params: {
    customerId: string;
    skuCode: string;
    quantity: number;
    shippingAddress: string;
    recipientName: string;
    recipientPhone: string;
  }): Promise<{ success: boolean; orderId?: string; message?: string }> {
    const pool = await this.ensureDb();

    // 1. 查询 SKU 详情并关联 SPU
    const skuRes = await pool.query(
      `
      SELECT s.*, p.title as spu_title, p.main_image as spu_image, p.id as spu_id
      FROM merchant_skus s
      JOIN merchant_spus p ON s.spu_id = p.id
      WHERE s.sku_code = $1
      LIMIT 1;
    `,
      [params.skuCode],
    );

    if (!skuRes.rows?.[0]) {
      return {
        success: false,
        message: `SKU 规格 [${params.skuCode}] 不存在或已下架`,
      };
    }

    const sku = skuRes.rows[0];
    if (sku.stock < params.quantity) {
      return {
        success: false,
        message: `库存不足：${sku.sku_title} 当前剩余 ${sku.stock} 件`,
      };
    }

    const orderId = `AURORA-ORD-2026-${Math.floor(1000 + Math.random() * 9000)}`;
    const payAmount = Number(sku.price) * params.quantity;
    const specSummary = Object.entries(sku.spec_attributes || {})
      .map(([k, v]) => `${k}:${v}`)
      .join(' / ');

    // 2. 事务执行扣减库存与落单
    const client = await pool.connect();
    try {
      await client.query('BEGIN');

      await client.query('UPDATE merchant_skus SET stock = stock - $1 WHERE sku_code = $2', [
        params.quantity,
        params.skuCode,
      ]);

      await client.query(
        `INSERT INTO merchant_orders (
          order_id, customer_id, status, total_amount, currency, shipping_address, is_returnable, is_address_modifiable
        ) VALUES ($1, $2, 'PAID', $3, 'CNY', $4, TRUE, TRUE)`,
        [
          orderId,
          params.customerId,
          payAmount,
          JSON.stringify({
            recipientName: params.recipientName,
            phone: params.recipientPhone,
            fullAddress: params.shippingAddress,
          }),
        ],
      );

      await client.query(
        `INSERT INTO merchant_order_items (
          order_id, spu_id, sku_code, title, sku_title, quantity, price, image_url, spec_summary
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
        [
          orderId,
          sku.spu_id,
          sku.sku_code,
          sku.spu_title,
          sku.sku_title,
          params.quantity,
          sku.price,
          sku.image_url || sku.spu_image,
          specSummary,
        ],
      );

      await client.query('COMMIT');
      return { success: true, orderId };
    } catch (err: unknown) {
      await client.query('ROLLBACK');
      const errMsg = err instanceof Error ? err.message : String(err);
      return { success: false, message: errMsg };
    } finally {
      client.release();
    }
  }

  /**
   * 7. 商户后台一键发货 (Admin Ship Order)
   */
  public static async shipOrder(params: {
    orderId: string;
    carrierCode: string;
    trackingNo: string;
  }): Promise<{ success: boolean; message?: string }> {
    const pool = await this.ensureDb();
    const trackingInfo = {
      carrier: params.carrierCode || 'SF',
      trackingNumber: params.trackingNo,
      status: 'IN_TRANSIT',
      latestLocation: '北京顺丰分拨中心',
      timeline: [
        {
          time: new Date().toISOString(),
          status: '揽收成功',
          location: '极光潮品华北一号仓',
          description: '包裹已由顺丰速运揽收并发出',
        },
      ],
    };

    const res = await pool.query(
      `UPDATE merchant_orders
       SET status = 'SHIPPED',
           tracking_info = $1,
           is_address_modifiable = FALSE
       WHERE order_id = $2`,
      [JSON.stringify(trackingInfo), params.orderId],
    );

    return {
      success: (res.rowCount ?? 0) > 0,
      message: (res.rowCount ?? 0) > 0 ? '发货成功，已流转为已发货状态并锁定地址' : '订单不存在',
    };
  }

  /**
   * 8. 获取商户全部后台订单、SPU/SKU库存矩阵与 SPI 审计日志
   */
  public static async getAdminDashboardData() {
    const pool = await this.ensureDb();
    const ordersRes = await pool.query('SELECT * FROM merchant_orders ORDER BY created_at DESC LIMIT 50');

    const logsRes = await pool.query('SELECT * FROM merchant_audit_logs ORDER BY created_at DESC LIMIT 50');

    // 查询 SPU 与其下的 SKU 汇总
    const spusRes = await pool.query('SELECT * FROM merchant_spus ORDER BY created_at ASC');
    const skusRes = await pool.query(
      `
      SELECT s.*, p.title as spu_title, p.brand, p.category
      FROM merchant_skus s
      JOIN merchant_spus p ON s.spu_id = p.id
      ORDER BY p.title, s.price ASC;
    `,
    );

    return {
      orders: ordersRes.rows,
      auditLogs: logsRes.rows,
      spus: spusRes.rows,
      inventory: skusRes.rows.map((r) => ({
        sku_code: r.sku_code,
        item_title: r.sku_title,
        selling_price: r.price,
        available_qty: r.stock,
        category_name: r.category,
        spec_attributes: r.spec_attributes,
      })),
      skus: skusRes.rows,
    };
  }
}
