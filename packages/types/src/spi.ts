/**
 * 标准第三方 SPI 开放契约 (Service Provider Interface)
 * 用于对接外部自研电商、Shopify、ERP/OMS、CRM 及多租户系统
 */

export interface ThirdPartyAddress {
  id?: string;
  recipientName: string;
  phone: string;
  fullAddress: string;
  province?: string;
  city?: string;
  district?: string;
  isDefault?: boolean;
}

export interface ThirdPartyUser {
  userId: string;
  name?: string;
  phone?: string;
  email?: string;
  memberLevel?: string;
  avatarUrl?: string;
  addresses?: ThirdPartyAddress[];
  tags?: string[];
  createdAt?: string;
}

export interface ThirdPartyOrderItem {
  skuId?: string;
  productId: string;
  title: string;
  quantity: number;
  price: string | number;
  imageUrl?: string;
  specSummary?: string;
}

export interface ThirdPartyTrackingTimelineItem {
  time: string;
  status: string;
  location?: string;
  description?: string;
}

export interface ThirdPartyTrackingInfo {
  carrier: string;
  trackingNumber: string;
  status: 'PENDING' | 'SHIPPED' | 'IN_TRANSIT' | 'OUT_FOR_DELIVERY' | 'DELIVERED' | 'EXCEPTION';
  latestLocation?: string;
  timeline?: ThirdPartyTrackingTimelineItem[];
}

export interface ThirdPartyOrder {
  orderId: string;
  userId: string;
  status: 'PENDING' | 'PAID' | 'PROCESSING' | 'SHIPPED' | 'DELIVERED' | 'CANCELLED' | 'REFUNDED';
  totalAmount: string | number;
  currency?: string;
  createdAt: string;
  items: ThirdPartyOrderItem[];
  shippingAddress: ThirdPartyAddress;
  tracking?: ThirdPartyTrackingInfo;
  isReturnable?: boolean;
  isAddressModifiable?: boolean;
}

export interface ThirdPartySku {
  skuCode: string;
  skuTitle: string;
  specAttributes: Record<string, string>; // e.g. {"颜色": "曜石黑", "尺码": "L (175/92A)"}
  price: number;
  originalPrice?: number;
  stock: number;
  imageUrl?: string;
  barCode?: string;
}

export interface ThirdPartySpecDimension {
  name: string; // e.g. "颜色", "尺码"
  values: string[]; // e.g. ["曜石黑", "极夜绿", "冰川白"]
}

export interface ThirdPartyProduct {
  productId: string; // SPU 或主 SKU ID
  spuId?: string;
  title: string;
  subtitle?: string;
  description?: string;
  price: string | number;
  originalPrice?: string | number;
  stock: number;
  category?: string;
  brand?: string;
  imageUrl?: string;
  detailImages?: string[];
  specDimensions?: ThirdPartySpecDimension[]; // SPU 包含的规格维度矩阵
  skus?: ThirdPartySku[]; // SPU 下拥有的具体 SKU 列表
  specs?: Record<string, string>; // 材质参数，例如 {"面料": "GORE-TEX 3L", "防水指数": "20000mmH2O"}
  isAvailable?: boolean;
}

export type ThirdPartyOrderActionType = 'MODIFY_ADDRESS' | 'CANCEL_ORDER' | 'REQUEST_REFUND' | 'CONFIRM_RECEIVED';

export interface ThirdPartyOrderActionRequest {
  actionType: ThirdPartyOrderActionType;
  orderId: string;
  userId?: string;
  idempotencyKey: string;
  newAddress?: string | ThirdPartyAddress;
  refundAmount?: string | number;
  reason?: string;
  evidenceImages?: string[];
  extra?: Record<string, unknown>;
}

export interface ThirdPartyOrderActionResult {
  success: boolean;
  actionType: ThirdPartyOrderActionType;
  orderId: string;
  actionId?: string;
  message?: string;
  newStatus?: string;
  updatedAddress?: string;
  refundId?: string;
  refundedAmount?: string | number;
  extra?: Record<string, unknown>;
}

export interface SpiResponse<T = unknown> {
  success: boolean;
  code?: string;
  message?: string;
  data?: T;
  timestamp?: number;
}

export type IntegrationMode = 'local_db' | 'remote_spi' | 'mcp_server';

export interface SpiConnectorConfig {
  mode: IntegrationMode;
  spiBaseUrl?: string;
  apiSecret?: string;
  mcpEndpoint?: string;
  timeoutMs?: number;
  customHeaders?: Record<string, string>;
  enableHmacSign?: boolean;
}
