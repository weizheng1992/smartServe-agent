import { db } from 'db';
import type {
  ThirdPartyAddress,
  ThirdPartyOrder,
  ThirdPartyOrderActionRequest,
  ThirdPartyOrderActionResult,
  ThirdPartyProduct,
  ThirdPartyUser,
} from 'types';
import { MallDomainService } from '../mallDomainService';
import { OrderDomainService } from '../orderDomainService';
import type { ThirdPartySpiClient } from './types';

/**
 * 平台内置本地数据库适配器 (Local Database Adapter)
 * 适配自营电商数据表与 Drizzle 领域服务，作为默认模式或无第三方独立系统的兜底运行底座
 */
export class LocalDbSpiAdapter implements ThirdPartySpiClient {
  public async getUserInfo(params: {
    userId?: string;
    userEmail?: string;
    threadId?: string;
    tenantId: string;
  }): Promise<ThirdPartyUser | null> {
    const rawAddresses = await OrderDomainService.getUserAddresses({
      userId: params.userId,
      userEmail: params.userEmail,
      threadId: params.threadId,
      businessId: params.tenantId,
    });

    const addresses: ThirdPartyAddress[] = rawAddresses.map((addr) => ({
      id: addr.id,
      recipientName: addr.receiverName,
      phone: addr.receiverPhone,
      fullAddress: addr.fullAddress,
      province: addr.province || undefined,
      city: addr.city || undefined,
      district: addr.district || undefined,
      isDefault: addr.isDefault || false,
    }));

    const defaultAddr = addresses.find((a) => a.isDefault) || addresses[0];

    return {
      userId: params.userId || 'anonymous_user',
      name: defaultAddr?.recipientName || '平台尊贵会员',
      phone: defaultAddr?.phone,
      email: params.userEmail,
      memberLevel: 'GOLD',
      addresses,
    };
  }

  public async listOrders(params: {
    userId?: string;
    userEmail?: string;
    threadId?: string;
    status?: string;
    tenantId: string;
    limit?: number;
  }): Promise<ThirdPartyOrder[]> {
    const orders = await OrderDomainService.getUserOrdersDetailed({
      userId: params.userId,
      userEmail: params.userEmail,
      threadId: params.threadId,
      businessId: params.tenantId,
    });

    return orders.map((o) => ({
      orderId: o.orderId,
      userId: params.userId || 'anonymous',
      status: (o.status?.toUpperCase() as ThirdPartyOrder['status']) || 'PENDING',
      totalAmount: o.totalAmount,
      currency: 'CNY',
      createdAt: o.createdAt ? String(o.createdAt) : new Date().toISOString(),
      items: (o.items || []).map((item) => ({
        skuId: 'SKU-DEFAULT',
        productId: 'PROD-DEFAULT',
        title: item.productName || '商品',
        quantity: item.quantity || 1,
        price: item.price || 0,
        imageUrl: item.imageUrl,
      })),
      shippingAddress: {
        id: o.addressId,
        recipientName: o.recipientName || '顾客',
        phone: o.phone || '',
        fullAddress: o.shippingAddress || '',
      },
      tracking: o.trackingNumber
        ? {
            carrier: o.carrier || 'SF',
            trackingNumber: o.trackingNumber,
            status: 'IN_TRANSIT',
            latestLocation: undefined,
          }
        : undefined,
      isReturnable: true,
      isAddressModifiable: ['PENDING', 'PAID', 'PROCESSING'].includes(o.status?.toUpperCase() || ''),
    }));
  }

  public async getOrderDetail(params: {
    orderId: string;
    tenantId: string;
  }): Promise<ThirdPartyOrder | null> {
    const order = await OrderDomainService.findOrderById(params.orderId, undefined, params.tenantId);
    if (!order) return null;

    const itemsRes = await db.execute(
      `SELECT oi.id, oi.product_id AS "productId", oi.quantity, oi.price_at_purchase AS "price", p.name AS "title"
       FROM order_items oi
       LEFT JOIN products p ON oi.product_id = p.id
       WHERE oi.order_id = $1`,
      [params.orderId],
    );
    const items = (itemsRes?.rows || []) as Array<{
      productId: string;
      quantity: number;
      price: number;
      title: string;
    }>;

    return {
      orderId: (order.orderId || order.order_id) as string,
      userId: (order.userId || order.user_id) as string,
      status: (order.status || 'PENDING').toUpperCase() as ThirdPartyOrder['status'],
      totalAmount: (order.totalAmount || order.total_amount || 0) as string | number,
      currency: 'CNY',
      createdAt: new Date().toISOString(),
      items: items.map((i) => ({
        skuId: i.productId || 'PROD-DEFAULT',
        productId: i.productId || 'PROD-DEFAULT',
        title: i.title || '商品',
        quantity: i.quantity || 1,
        price: i.price || '0.00',
      })),
      shippingAddress: {
        recipientName: '收件人',
        phone: '',
        fullAddress: '北京市海淀区中关村南大街1号院',
      },
      isReturnable: true,
      isAddressModifiable: ['PENDING', 'PAID', 'PROCESSING'].includes((order.status || '').toUpperCase()),
    };
  }

  public async executeOrderAction(
    req: ThirdPartyOrderActionRequest & { tenantId: string },
  ): Promise<ThirdPartyOrderActionResult> {
    if (req.actionType === 'REQUEST_REFUND') {
      const refundAmountStr = typeof req.refundAmount === 'number' ? req.refundAmount.toFixed(2) : req.refundAmount;

      const res = await OrderDomainService.processRefund(
        req.orderId,
        req.reason || 'SOP 标准退款申请',
        undefined,
        refundAmountStr,
      );

      return {
        success: Boolean(res.refundedAmount || res.message?.includes('成功')),
        actionType: 'REQUEST_REFUND',
        orderId: req.orderId,
        actionId: req.idempotencyKey,
        refundId: (res.auditTrail as { approvalId?: string })?.approvalId || `REFUND_${Date.now()}`,
        refundedAmount: (res.refundedAmount as string | number | undefined) || req.refundAmount,
        message: res.error || res.message || '退款处理成功',
      };
    }

    if (req.actionType === 'MODIFY_ADDRESS') {
      const newAddressStr = typeof req.newAddress === 'string' ? req.newAddress : req.newAddress?.fullAddress || '';

      const res = await OrderDomainService.changeShippingAddress(req.orderId, newAddressStr, undefined, true);

      return {
        success: !res.error,
        actionType: 'MODIFY_ADDRESS',
        orderId: req.orderId,
        actionId: req.idempotencyKey,
        updatedAddress: newAddressStr,
        message: res.error || res.message || (!res.error ? '收货地址修改成功' : '修改地址失败'),
      };
    }

    return {
      success: false,
      actionType: req.actionType,
      orderId: req.orderId,
      message: `未支持的操作动作: ${req.actionType}`,
    };
  }

  public async searchProducts(params: {
    query: string;
    category?: string;
    tenantId: string;
    limit?: number;
  }): Promise<ThirdPartyProduct[]> {
    const productsRes = await db.execute(
      `SELECT id, name AS "title", category, price, stock
       FROM products
       WHERE (business_id = $1 OR $1 = 'ecommerce')
       AND ($2::text IS NULL OR name ILIKE '%' || $2 || '%' OR category ILIKE '%' || $2 || '%')
       LIMIT $3`,
      [params.tenantId, params.query || null, params.limit || 5],
    );

    const rows = (productsRes?.rows || []) as Array<{
      id: string;
      title: string;
      category?: string;
      price: number;
      stock: number;
    }>;

    return rows.map((p) => ({
      productId: p.id,
      title: p.title,
      description: '',
      price: p.price,
      originalPrice: undefined,
      stock: p.stock || 0,
      category: p.category || undefined,
      imageUrl: undefined,
      isAvailable: (p.stock || 0) > 0,
    }));
  }
}
