import type {
  ThirdPartyAddress,
  ThirdPartyOrder,
  ThirdPartyOrderActionRequest,
  ThirdPartyOrderActionResult,
  ThirdPartyProduct,
  ThirdPartyUser,
} from 'types';

export interface ThirdPartySpiClient {
  /**
   * 获取用户信息与地址簿
   */
  getUserInfo(params: {
    userId?: string;
    userEmail?: string;
    threadId?: string;
    tenantId: string;
  }): Promise<ThirdPartyUser | null>;

  /**
   * 查询用户订单列表
   */
  listOrders(params: {
    userId?: string;
    userEmail?: string;
    threadId?: string;
    status?: string;
    tenantId: string;
    limit?: number;
  }): Promise<ThirdPartyOrder[]>;

  /**
   * 查询指定订单明细与物流
   */
  getOrderDetail(params: {
    orderId: string;
    tenantId: string;
  }): Promise<ThirdPartyOrder | null>;

  /**
   * 执行订单变更与售后履约 (改地址 / 发起退款 / 取消订单)
   */
  executeOrderAction(req: ThirdPartyOrderActionRequest & { tenantId: string }): Promise<ThirdPartyOrderActionResult>;

  /**
   * 搜索商品库与现货库存
   */
  searchProducts(params: {
    query: string;
    category?: string;
    tenantId: string;
    limit?: number;
  }): Promise<ThirdPartyProduct[]>;
}
