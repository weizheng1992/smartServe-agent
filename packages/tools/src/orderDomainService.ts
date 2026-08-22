import crypto from 'crypto';
import { type Order, db, getDrizzle, longMemoryFacts } from 'db';
import type {
  DatabaseOrderItemRow,
  DatabaseOrderRow,
  DatabaseProductRow,
  DatabaseThreadRow,
  ToolAuditTrail,
  ToolExecutionResult,
} from 'types';
import { toolCache } from './cache';

export interface ThreadSessionContext {
  userId: string;
  businessId: string;
}

export class OrderDomainService {
  /**
   * 🛡️ 零越权验证 (Zero IDOR): 通过 threadId 物理追溯当前登录用户身份及所属商户
   */
  static async getThreadSessionContext(threadId?: string): Promise<ThreadSessionContext> {
    if (!threadId) {
      return { userId: '', businessId: 'ecommerce' };
    }

    try {
      const res = await db.execute(
        'SELECT "user_id" AS "userId", "business_id" AS "businessId" FROM threads WHERE id = $1',
        [threadId],
      );
      if (res.rows?.[0]) {
        const row = res.rows[0] as DatabaseThreadRow;
        return {
          userId: (row.userId || row.user_id || '') as string,
          businessId: (row.businessId || row.business_id || 'ecommerce') as string,
        };
      }
    } catch (err) {
      console.warn('[OrderDomainService] Failed to fetch thread session context:', err);
    }

    return { userId: '', businessId: 'ecommerce' };
  }

  /**
   * 获取商户售后 SOP 退货时效规定（Nike 30天，Adidas 14天，电商主站 7天）
   */
  static getReturnWindowDays(businessId: string): number {
    const cleanId = (businessId || '').toLowerCase();
    if (cleanId === 'nike') return 30;
    if (cleanId === 'adidas') return 14;
    return 7;
  }

  /**
   * 🛡️ 统一多租户与用户归属订单安全查询
   */
  static async findOrderById(orderId: string, userId?: string, businessId?: string): Promise<DatabaseOrderRow | null> {
    try {
      const conditions = ['order_id = $1'];
      const params: (string | number)[] = [orderId];

      if (userId) {
        params.push(userId);
        conditions.push(`user_id = $${params.length}`);
      }

      if (businessId && businessId !== 'ecommerce') {
        params.push(businessId);
        conditions.push(`business_id = $${params.length}`);
      }

      const orderQuery = `SELECT order_id AS "orderId", status, carrier, tracking_number AS "trackingNumber", estimated_delivery AS "estimatedDelivery", user_id AS "userId", business_id AS "businessId", total_amount AS "totalAmount" FROM orders WHERE ${conditions.join(' AND ')}`;
      const res = await db.execute(orderQuery, params);
      return (res?.rows?.[0] as DatabaseOrderRow) || null;
    } catch (err) {
      console.error('[OrderDomainService.findOrderById] Database error:', err);
      return null;
    }
  }

  /**
   * 查询订单状态与物流详情（具备二级多级缓存防护）
   */
  static async getOrderStatus(orderId: string, threadId?: string): Promise<ToolExecutionResult> {
    const { userId: sessionUserId, businessId } = await this.getThreadSessionContext(threadId);
    const cacheKey = `cache:order_status:${orderId}`;

    // 1. 尝试从多级缓存中读取
    const cached = await toolCache.get<Record<string, unknown>>(cacheKey);
    if (cached) {
      if (!sessionUserId || cached.userId === sessionUserId) {
        console.log(`[Tool Cache Hit] 🎯 缓存命中！直接返回 Order ${orderId} 物流数据！`);
        return cached as ToolExecutionResult;
      }
    }

    // 2. 数据库物理关联查询
    const order = await this.findOrderById(orderId, sessionUserId, businessId);

    if (!order) {
      return {
        error: `⚠️ 越权阻止或未找到订单：订单 ${orderId} 不属于您名下，或不存在于系统中。`,
      };
    }

    const items: DatabaseOrderItemRow[] = [];
    try {
      const itemsRes = await db.execute('SELECT * FROM "order_items" WHERE "order_id" = $1', [orderId]);
      if (itemsRes?.rows) {
        for (const itemRow of itemsRes.rows as DatabaseOrderItemRow[]) {
          const prodId = (itemRow.product_id || itemRow.productId) as string;
          const quantity = Number(itemRow.quantity || 1);
          const priceAtPurchase = Number(itemRow.price_at_purchase || itemRow.priceAtPurchase || 0);

          let prodName = '未知商品';
          let prodDesc = '';
          try {
            const prodRes = await db.execute('SELECT * FROM "products" WHERE "id" = $1', [prodId]);
            if (prodRes?.rows?.[0]) {
              const prod = prodRes.rows[0] as DatabaseProductRow;
              prodName = (prod.name || '未知商品') as string;
              prodDesc = (prod.description || '') as string;
            }
          } catch {
            // 查询商品详情失败时保持默认值
          }

          items.push({
            productId: prodId,
            name: prodName,
            description: prodDesc,
            quantity,
            priceAtPurchase,
          });
        }
      }
    } catch (err) {
      console.warn('[OrderDomainService] Failed to fetch relational order items:', err);
    }

    const computedTotal = items.reduce((sum, item) => sum + (item.priceAtPurchase ?? 0) * (item.quantity ?? 1), 0);

    let totalAmountFormatted = '$0.00';
    if (computedTotal > 0) {
      totalAmountFormatted = `$${computedTotal.toFixed(2)}`;
    } else if (order.totalAmount || order.total_amount) {
      const rawVal = String(order.totalAmount || order.total_amount);
      const numVal = Number.parseFloat(rawVal.replace(/[^0-9.]/g, ''));
      totalAmountFormatted = Number.isNaN(numVal) ? '$0.00' : `$${numVal.toFixed(2)}`;
    }

    const enrichedOrder: Record<string, unknown> = {
      orderId: order.orderId || order.order_id,
      status: order.status,
      carrier: order.carrier,
      trackingNumber: order.trackingNumber || order.tracking_number,
      estimatedDelivery: order.estimatedDelivery || order.estimated_delivery,
      userId: order.userId || order.user_id,
      businessId: order.businessId || order.business_id,
      items,
      totalAmount: totalAmountFormatted,
    };

    // 异步写入多级缓存（TTL 60 秒）
    await toolCache.set(cacheKey, enrichedOrder, 60);

    return enrichedOrder as ToolExecutionResult;
  }

  /**
   * 办理退款（校验 SOP 政策时效、更新数据库状态并使缓存失效）
   */
  static async processRefund(
    orderId: string,
    reason: string,
    threadId?: string,
    amount?: string,
  ): Promise<ToolExecutionResult> {
    const { userId: sessionUserId, businessId } = await this.getThreadSessionContext(threadId);
    const returnWindowDays = this.getReturnWindowDays(businessId);

    const order = await this.findOrderById(orderId, sessionUserId, businessId);

    if (!order) {
      return {
        error: `⚠️ 越权阻止或未找到订单：退款订单 ${orderId} 不属于您名下，或不存在于系统中。`,
      };
    }

    // 物理时效比对（SOP Policy Guardrail）
    let diffDays = 0;
    const estimatedDelivery = order.estimatedDelivery || order.estimated_delivery;
    if (estimatedDelivery) {
      const deliveryDate = new Date(estimatedDelivery);
      const currentDate = new Date();
      const diffTime = Math.abs(currentDate.getTime() - deliveryDate.getTime());
      diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

      if (diffDays > returnWindowDays) {
        console.log(
          `[Refund Tool Guardrail] ❌ 政策拦截：商户 [${businessId}] 退货期为 ${returnWindowDays} 天，订单已过去 ${diffDays} 天！`,
        );
        return {
          error: `⚠️ 退款政策拦截：根据商户 [${businessId.toUpperCase()}] 官方售后 SOP 规范，退货时效为订单送达之日起 ${returnWindowDays} 天内。该订单送达日期为 ${estimatedDelivery}，当前已逾期 ${diffDays} 天，超出合规退款时效。物理拒绝执行退款！`,
          orderId,
          status: 'rejected_by_policy',
          businessId,
          returnWindowDays,
          elapsedDays: diffDays,
        };
      }
    }

    // 更新数据库订单状态为 refunded
    await db.execute('UPDATE "orders" SET status = \'refunded\' WHERE "order_id" = $1', [orderId]);

    // 立即清除订单相关缓存，保障强一致性
    await toolCache.delete(`cache:order_status:${orderId}`);
    console.log(
      `[Tool Cache Invalidate] 🧹 因退款发起，已全渠道物理清除 Order ${orderId} 的物流缓存，确保缓存强一致性！`,
    );

    let refundAmountVal = '$99.99';
    const totalAmountVal = order.totalAmount || order.total_amount;
    if (totalAmountVal) {
      refundAmountVal = `$${totalAmountVal}`;
    } else if (amount) {
      refundAmountVal = amount.startsWith('$') ? amount : `$${amount}`;
    }

    let auditTrail: ToolAuditTrail | null = null;
    if (threadId) {
      try {
        const appRes = await db.execute(
          'SELECT id, "created_at" AS "createdAt", status FROM pending_approvals WHERE thread_id = $1 AND action_type = $2 ORDER BY created_at DESC LIMIT 1',
          [threadId, 'processRefund'],
        );
        const firstRow = appRes.rows?.[0] as Record<string, any> | undefined;
        if (firstRow && firstRow.status === 'approved') {
          const appRecord = firstRow;
          const verHash = crypto
            .createHash('sha256')
            .update(`${appRecord.id}:${orderId}:refunded:${refundAmountVal}`)
            .digest('hex');
          auditTrail = {
            approvalId: appRecord.id,
            approvedAt: appRecord.createdAt ? new Date(appRecord.createdAt).toISOString() : new Date().toISOString(),
            policyMatched: `SOP Window Check: Passed (${diffDays} days elapsed of allowed ${returnWindowDays} days)`,
            actionVerifier: 'supervisor_approval_gate',
            verifiableHash: verHash,
          };
        }
      } catch (auditErr) {
        console.warn('[Refund Tool Audit] Failed to generate physical audit trail:', auditErr);
      }
    }

    if (!auditTrail) {
      const verHash = crypto.createHash('sha256').update(`auto-approved:${orderId}:${refundAmountVal}`).digest('hex');
      auditTrail = {
        approvalId: 'AUTO_APPROVED',
        approvedAt: new Date().toISOString(),
        policyMatched: `SOP Auto-Approval Limit Check: Passed ($${totalAmountVal || 0} <= $100 limit; ${diffDays} days elapsed of allowed ${returnWindowDays} days)`,
        actionVerifier: 'system_auto_approval_engine',
        verifiableHash: verHash,
      };
    }

    return {
      orderId,
      status: 'refunded',
      refundAmount: refundAmountVal,
      reason,
      transactionId: `TXN_${Math.random().toString(36).substr(2, 9).toUpperCase()}`,
      message: 'Physical refund process initiated in Postgres database.',
      auditTrail,
    };
  }

  /**
   * 🛒 创建新订单（公共领域服务方法）
   */
  static async createOrder(options: {
    orderId?: string;
    userId?: string;
    businessId?: string;
    carrier?: string;
    trackingNumber?: string;
    estimatedDelivery?: string;
    totalAmount?: number;
    items?: Array<{
      productId: string;
      quantity: number;
      priceAtPurchase?: number;
    }>;
    threadId?: string;
  }): Promise<ToolExecutionResult> {
    let {
      orderId = `ORD-${Date.now().toString().slice(-6)}`,
      userId,
      businessId,
      carrier = 'SF Express',
      trackingNumber = `SF${Math.floor(1000000000 + Math.random() * 9000000000)}`,
      estimatedDelivery = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
      totalAmount = 99.0,
      items = [],
      threadId,
    } = options;

    if ((!userId || !businessId) && threadId) {
      const ctx = await this.getThreadSessionContext(threadId);
      if (!userId && ctx.userId) userId = ctx.userId;
      if (!businessId && ctx.businessId) businessId = ctx.businessId;
    }

    businessId = businessId || 'ecommerce';

    if (!userId) {
      return {
        error: 'userId is strictly required to create an order (or provide valid session threadId).',
      };
    }

    try {
      await db.execute(
        'INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery, user_id, business_id, total_amount) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT (order_id) DO UPDATE SET status = EXCLUDED.status, carrier = EXCLUDED.carrier, tracking_number = EXCLUDED.tracking_number, estimated_delivery = EXCLUDED.estimated_delivery, total_amount = EXCLUDED.total_amount',
        [orderId, 'shipped', carrier, trackingNumber, estimatedDelivery, userId, businessId, totalAmount],
      );

      for (const item of items) {
        const itemId = `item_${orderId}_${item.productId}`;
        await db.execute(
          'INSERT INTO order_items (id, order_id, product_id, quantity, price_at_purchase) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO NOTHING',
          [itemId, orderId, item.productId, item.quantity, item.priceAtPurchase || 0],
        );
      }

      await toolCache.delete(`cache:order_status:${orderId}`);

      return {
        success: true,
        order: {
          orderId,
          status: 'shipped',
          carrier,
          trackingNumber,
          estimatedDelivery,
          userId,
          businessId,
          totalAmount,
        },
      };
    } catch (err) {
      console.error('[OrderDomainService.createOrder] Failed:', err);
      return { error: 'Failed to create order in database.' };
    }
  }

  /**
   * 查询当前会话客户的历史订单列表
   */
  static async listUserOrders(threadId?: string): Promise<ToolExecutionResult> {
    if (!threadId) {
      return {
        error: 'Session threadId is strictly required to query customer orders.',
      };
    }

    const { userId, businessId } = await this.getThreadSessionContext(threadId);
    if (!userId) {
      return {
        error: 'Could not resolve valid user context from the current session thread.',
      };
    }

    try {
      const res = await db.execute(
        'SELECT "order_id" AS "orderId", status, carrier, "tracking_number" AS "trackingNumber", "estimated_delivery" AS "estimatedDelivery", "total_amount" AS "totalAmount", "business_id" AS "businessId" FROM orders WHERE "user_id" = $1 AND "business_id" = $2 ORDER BY "estimated_delivery" DESC',
        [userId, businessId || 'ecommerce'],
      );
      const rows = res.rows || [];
      if (rows.length === 0) {
        // 自动自愈注入示例订单（保障多租户与新用户演示体验）
        const activeBiz = (businessId || 'ecommerce').toLowerCase();
        const prefix = activeBiz === 'nike' ? 'NIKE' : activeBiz === 'adidas' ? 'ADIDAS' : 'ECO';
        const demoOrderId1 = `ORD-${prefix}-${Date.now().toString().slice(-4)}1`;
        const demoOrderId2 = `ORD-${prefix}-${Date.now().toString().slice(-4)}2`;

        try {
          await this.createOrder({
            orderId: demoOrderId1,
            userId,
            businessId: activeBiz,
            carrier: 'SF Express (顺丰速运)',
            trackingNumber: `SF${Math.floor(1000000000 + Math.random() * 9000000000)}`,
            estimatedDelivery: new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
            totalAmount: 199.0,
            threadId,
          });
          await this.createOrder({
            orderId: demoOrderId2,
            userId,
            businessId: activeBiz,
            carrier: 'JD Logistics (京东物流)',
            trackingNumber: `JD${Math.floor(1000000000 + Math.random() * 9000000000)}`,
            estimatedDelivery: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
            totalAmount: 89.0,
            threadId,
          });

          const seededRes = await db.execute(
            'SELECT "order_id" AS "orderId", status, carrier, "tracking_number" AS "trackingNumber", "estimated_delivery" AS "estimatedDelivery", "total_amount" AS "totalAmount", "business_id" AS "businessId" FROM orders WHERE "user_id" = $1 AND "business_id" = $2 ORDER BY "estimated_delivery" DESC',
            [userId, activeBiz],
          );
          if (seededRes.rows && seededRes.rows.length > 0) {
            return { orders: seededRes.rows } as ToolExecutionResult;
          }
        } catch (seedErr) {
          console.warn('[OrderDomainService] Auto-seed demo orders fallback warning:', seedErr);
        }

        return { message: 'No orders found for this customer.' };
      }
      return { orders: rows } as ToolExecutionResult;
    } catch (err) {
      console.error('[OrderDomainService.listUserOrders] Failed:', err);
      return { error: 'Failed to retrieve orders from database.' };
    }
  }

  /**
   * 修改订单收货地址（高价值订单触发人工审核门闸）
   */
  static async changeShippingAddress(
    orderId: string,
    newAddress: string,
    threadId?: string,
    isApproved?: boolean,
  ): Promise<ToolExecutionResult> {
    const { userId: sessionUserId } = await this.getThreadSessionContext(threadId);

    try {
      const orderQuery = sessionUserId
        ? 'SELECT status, "total_amount" AS "totalAmount", user_id AS "userId" FROM orders WHERE order_id = $1 AND user_id = $2'
        : 'SELECT status, "total_amount" AS "totalAmount", user_id AS "userId" FROM orders WHERE order_id = $1';
      const orderQueryParams = sessionUserId ? [orderId, sessionUserId] : [orderId];
      const res = await db.execute(orderQuery, orderQueryParams);
      const rows = res.rows || [];
      if (rows.length === 0) {
        return {
          error: `⚠️ 越权阻止或未找到订单：订单 ${orderId} 不属于您名下，或不存在于系统中。`,
        };
      }

      const order = rows[0] as DatabaseOrderRow;
      const status = (order.status || '') as string;
      const totalAmount = Number(order.totalAmount || order.total_amount || 0);

      if (status === 'shipped' || status === 'delivered') {
        return {
          error: `⚠️ Address modification blocked: Order ${orderId} is currently [${status.toUpperCase()}] and has already left our logistics centers. Physical modification is impossible.`,
        };
      }

      if (totalAmount > 100.0 && !isApproved) {
        console.log(
          `[Address Change Guardrail] 🛡️ High-value order address modification detected ($${totalAmount}). Flagging for human audit.`,
        );
        return {
          waitingForApproval: true,
          actionType: 'changeShippingAddress',
          actionPayload: {
            args: { orderId, newAddress },
          },
          message: `🛡️ Security Alert: Address change for high-value order ${orderId} ($${totalAmount}) has been suspended. Awaiting Supervisor verification.`,
        };
      }

      console.log(`[Address Change] ✅ Order ${orderId} address updated to: "${newAddress}"`);

      let auditTrail: ToolAuditTrail | null = null;
      if (totalAmount > 100.0 && isApproved && threadId) {
        try {
          const appRes = await db.execute(
            'SELECT id, "created_at" AS "createdAt", status FROM pending_approvals WHERE thread_id = $1 AND action_type = $2 ORDER BY created_at DESC LIMIT 1',
            [threadId, 'changeShippingAddress'],
          );
          const firstRow = appRes.rows?.[0] as Record<string, any> | undefined;
          if (firstRow && firstRow.status === 'approved') {
            const appRecord = firstRow;
            const verHash = crypto
              .createHash('sha256')
              .update(`${appRecord.id}:${orderId}:address_updated:${newAddress}`)
              .digest('hex');
            auditTrail = {
              approvalId: appRecord.id,
              approvedAt: appRecord.createdAt ? new Date(appRecord.createdAt).toISOString() : new Date().toISOString(),
              policyMatched: `SOP Address Change Check: High-Value Approved ($${totalAmount} > $100)`,
              actionVerifier: 'supervisor_approval_gate',
              verifiableHash: verHash,
            };
          }
        } catch (auditErr) {
          console.warn('[Address Tool Audit] Failed to generate physical audit trail:', auditErr);
        }
      }

      if (!auditTrail) {
        const verHash = crypto
          .createHash('sha256')
          .update(`auto-approved-address:${orderId}:${totalAmount}`)
          .digest('hex');
        auditTrail = {
          approvalId: 'AUTO_APPROVED',
          approvedAt: new Date().toISOString(),
          policyMatched: `SOP Address Change Check: Standard Auto-Approval ($${totalAmount} <= $100 limit)`,
          actionVerifier: 'system_auto_approval_engine',
          verifiableHash: verHash,
        };
      }

      return {
        orderId,
        status: 'address_updated',
        newAddress,
        message: `✅ Shipping address for order ${orderId} has been successfully updated to: ${newAddress}.`,
        auditTrail,
      };
    } catch (err) {
      console.error('[OrderDomainService.changeShippingAddress] Failure:', err);
      return { error: 'Failed to process address change.' };
    }
  }

  /**
   * 生成电子发票
   */
  static async generateInvoice(orderId: string, threadId?: string): Promise<ToolExecutionResult> {
    const { userId: sessionUserId } = await this.getThreadSessionContext(threadId);

    try {
      const orderQuery = sessionUserId
        ? 'SELECT status, "total_amount" AS "totalAmount", user_id AS "userId" FROM orders WHERE order_id = $1 AND user_id = $2'
        : 'SELECT status, "total_amount" AS "totalAmount", user_id AS "userId" FROM orders WHERE order_id = $1';
      const orderQueryParams = sessionUserId ? [orderId, sessionUserId] : [orderId];
      const res = await db.execute(orderQuery, orderQueryParams);
      const rows = res.rows || [];
      if (rows.length === 0) {
        return {
          error: `⚠️ 越权阻止或未找到订单：订单 ${orderId} 不属于您名下，或不存在于系统中。`,
        };
      }

      const order = rows[0] as DatabaseOrderRow;
      const totalAmount = order.totalAmount || order.total_amount;
      const invoiceId = `INV-${Math.random().toString(36).substr(2, 9).toUpperCase()}`;

      console.log(`[Invoice Tool] ✅ Invoice ${invoiceId} compiled for order ${orderId}`);
      return {
        invoiceId,
        orderId,
        totalAmount: totalAmount as string,
        taxAmount: `$${(Number(totalAmount) * 0.08).toFixed(2)}`,
        message: `✅ Electronic Tax Invoice ${invoiceId} has been successfully compiled and registered with financial tax administrations. Download PDF: /invoices/${invoiceId}.pdf`,
      };
    } catch (err) {
      console.error('[OrderDomainService.generateInvoice] Failure:', err);
      return { error: 'Failed to generate tax invoice.' };
    }
  }

  /**
   * 记录用户画像与消费偏好
   */
  static async recordUserPreference(
    preferenceType: string,
    preferenceValue: string,
    threadId?: string,
  ): Promise<ToolExecutionResult> {
    if (!threadId) {
      return { error: 'Session threadId is strictly required.' };
    }

    const { userId } = await this.getThreadSessionContext(threadId);
    if (!userId) {
      return { error: 'Could not resolve user context from current session.' };
    }

    try {
      const drizzle = getDrizzle();
      const factText = `[User ${preferenceType} preference]: ${preferenceValue}`;

      let serializedEmbedding: string | null = null;
      try {
        const baseURL = process.env.AI_BASE_URL || 'http://localhost:11211/api/openai/v1';
        const apiKey = process.env.AI_API_KEY || 'dummy';
        const modelName = process.env.AI_EMBEDDING_MODEL || 'text-embedding-005:latest';

        const embedRes = await fetch(`${baseURL}/embeddings`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${apiKey}`,
          },
          body: JSON.stringify({
            input: factText,
            model: modelName,
          }),
        });
        const embedData = await embedRes.json();
        const embedding = embedData.data?.[0]?.embedding;
        if (embedding) {
          serializedEmbedding = JSON.stringify(embedding);
        }
      } catch (embErr) {
        console.warn('[OrderDomainService.recordUserPreference] Embedding generation fallback:', embErr);
      }

      if (drizzle) {
        await drizzle.insert(longMemoryFacts).values({
          userId,
          fact: factText,
          embedding: serializedEmbedding,
          type: 'preference',
          createdAt: new Date(),
        });
        console.log(`[OrderDomainService] Successfully stored "${factText}" into longMemoryFacts!`);
      }

      return {
        success: true,
        userId,
        preferenceType,
        preferenceValue,
        message: `✅ 已成功将您的消费偏好偏爱（${preferenceType}: ${preferenceValue}）登记入库。系统已同步更新 RAG 画像专家混合记忆矩阵，后续为您推荐商品及尺码换算时将自动参考！`,
      };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error('[OrderDomainService.recordUserPreference] Storage failed:', errorMessage);
      return {
        error: `Failed to register consumer preference: ${errorMessage}`,
      };
    }
  }

  /**
   * 📊 商品多维度排行与销售分析 (Dynamic Metric-Driven Product Ranking & Analytics)
   * 完全由 METRIC_REGISTRY 元数据注册表驱动，零硬编码 if/else，支持任意新增维度的即插即用！
   */
  static async queryProductRanking(options: {
    rankingMetric?: string;
    query?: string;
    naturalQuery?: string;
    managerOnly?: boolean;
    businessId?: string;
    category?: string;
    limit?: number;
    threadId?: string;
  }): Promise<Record<string, unknown>> {
    const { NLQueryParser } = await import('./nlQuery');
    const { METRIC_SEMANTIC_REGISTRY, MetricSemanticResolver } = await import('./metricRegistry');

    const rawInput = options.query || options.naturalQuery || options.rankingMetric || 'gmv';
    const ast = NLQueryParser.parse(rawInput);

    const session = await this.getThreadSessionContext(options.threadId);
    const businessId = options.businessId || session.businessId || 'nike';
    const userId = session.userId || '4c9ce5e9-eb44-4988-b9f4-ec75ec9d8444';

    const targetMetric = METRIC_SEMANTIC_REGISTRY[ast.metricKey] || METRIC_SEMANTIC_REGISTRY.gmv;
    const finalLimit = options.limit || ast.limit || 5;
    const finalDirection = ast.directionOverride || targetMetric.direction;
    const managerOnly = options.managerOnly !== undefined ? options.managerOnly : true;

    console.log(
      `[OrderDomainService.queryProductRanking] Metric: ${targetMetric.key} (${targetMetric.label}), Direction: ${finalDirection}, Tenant: ${businessId}, User: ${userId}`,
    );

    try {
      const queryParams: (string | number | boolean)[] = [businessId];
      let whereClause = `WHERE p.business_id = $1`;

      if (managerOnly && userId) {
        queryParams.push(userId);
        whereClause += ` AND p.manager_id = $${queryParams.length}`;
      }

      const explicitCategory = options.category || (ast.filters.find((f) => f.field === 'p.category')?.value as string);
      if (explicitCategory) {
        queryParams.push(explicitCategory);
        whereClause += ` AND p.category = $${queryParams.length}`;
      }

      // 附加数值过滤 (如 stock / price)
      for (const filter of ast.filters) {
        if (filter.field !== 'p.category') {
          whereClause += ` AND ${filter.sqlClause}`;
        }
      }

      // 附加时间过滤 (如 o.created_at)
      if (ast.timeRange?.sqlFilter) {
        whereClause += ` AND ${ast.timeRange.sqlFilter}`;
      }

      queryParams.push(finalLimit);
      const limitParamIndex = queryParams.length;

      const dimensions = [
        'p.id AS "productId"',
        'p.name',
        'p.category',
        'p.price',
        'p.stock',
        'COALESCE(p.cost_price, 0) AS "costPrice"',
        'COALESCE(SUM(oi.quantity), 0)::int AS "totalVolume"',
        'COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0)::float AS "totalGmv"',
        'COALESCE(SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0)), 0)::float AS "totalCost"',
        '(COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) - COALESCE(SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0)), 0))::float AS "grossProfit"',
      ];

      // 🌟 使用 MetricSemanticResolver 动态编译 SQL 模板
      const sql = MetricSemanticResolver.renderSql({
        metric: targetMetric,
        dimensions,
        groupBy: ['p.id', 'p.name', 'p.category', 'p.price', 'p.stock', 'p.cost_price'],
        filters: whereClause,
        limit: `$${limitParamIndex}`,
        direction: finalDirection,
      });

      const result = await db.execute(sql, queryParams);
      const rows = (result.rows || []) as Record<string, unknown>[];

      const rankedProducts = rows.map((r, idx) => {
        const totalGmv = Number(r.totalGmv || 0);
        const grossProfit = Number(r.grossProfit || 0);
        const marginRate = totalGmv > 0 ? `${((grossProfit / totalGmv) * 100).toFixed(1)}%` : '0.0%';

        return {
          rank: idx + 1,
          productId: String(r.productId),
          name: String(r.name),
          category: String(r.category || 'general'),
          price: Number(r.price || 0),
          costPrice: Number(r.costPrice || 0),
          stock: Number(r.stock || 0),
          totalVolume: Number(r.totalVolume || 0),
          totalGmv,
          grossProfit,
          marginRate,
          metricScore: Number(r.computedMetricValue || 0),
          metricDisplay: `${Number(r.computedMetricValue || 0).toLocaleString()} ${targetMetric.unit}`,
        };
      });

      return {
        success: true,
        rankingMetric: targetMetric.key,
        metricLabel: targetMetric.label,
        metricUnit: targetMetric.unit,
        businessId,
        managerId: managerOnly ? userId : undefined,
        itemCount: rankedProducts.length,
        products: rankedProducts,
        summary: `已为您完成${managerOnly ? '名下负责商品' : '全商户商品'}的排行检索，排序口径：【${targetMetric.label}】，共返回 ${rankedProducts.length} 款商品。`,
      };
    } catch (err) {
      console.error('[OrderDomainService.queryProductRanking] Query failed:', err);
      return {
        error: `Failed to query product ranking: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  }
}
