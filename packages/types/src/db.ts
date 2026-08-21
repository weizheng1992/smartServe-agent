export interface DatabaseOrderRow {
  orderId?: string;
  order_id?: string;
  status?: string;
  carrier?: string;
  trackingNumber?: string;
  tracking_number?: string;
  estimatedDelivery?: string;
  estimated_delivery?: string;
  userId?: string;
  user_id?: string;
  businessId?: string;
  business_id?: string;
  totalAmount?: string | number;
  total_amount?: string | number;
  [key: string]: unknown;
}

export interface DatabaseOrderItemRow {
  productId?: string;
  product_id?: string;
  quantity?: number;
  priceAtPurchase?: number;
  price_at_purchase?: number;
  costAtPurchase?: number;
  cost_at_purchase?: number;
  name?: string;
  description?: string;
  [key: string]: unknown;
}

export interface DatabaseProductRow {
  id?: string;
  name?: string;
  businessId?: string;
  business_id?: string;
  managerId?: string;
  manager_id?: string;
  category?: string;
  description?: string;
  price?: number;
  costPrice?: number;
  cost_price?: number;
  stock?: number;
  [key: string]: unknown;
}

export interface DatabaseThreadRow {
  id?: string;
  userId?: string;
  user_id?: string;
  businessId?: string;
  business_id?: string;
  title?: string;
  updatedAt?: string | Date;
  [key: string]: unknown;
}

export interface AnalyticsSummaryRow {
  date?: string;
  totalChats?: number;
  autopilotResolved?: number;
  humanEscalated?: number;
  refundsProcessed?: number;
  estimatedCostUsd?: number;
  [key: string]: unknown;
}

export interface TenantRow {
  id: string;
  businessId: string;
  name: string;
  planTier: 'free' | 'pro' | 'enterprise';
  status: 'active' | 'suspended';
  createdAt?: string | Date;
}

export interface TenantMemberRow {
  id: string;
  tenantId: string;
  userId: string;
  role: 'owner' | 'admin' | 'agent';
  createdAt?: string | Date;
}

export interface TenantConfigRow {
  id: string;
  businessId: string;
  systemPrompt?: string | null;
  welcomeMessage?: string | null;
  temperature?: number | null;
  status: 'draft' | 'published';
  version: number;
  updatedAt?: string | Date;
}

export interface TenantToolRow {
  id: string;
  tenantId: string;
  name: string;
  description?: string | null;
  schema: Record<string, unknown>;
  authType: 'none' | 'bearer' | 'basic' | 'custom_header';
  encryptedCredentials?: string | null;
  requiresApproval: boolean;
  enabled: boolean;
  createdAt?: string | Date;
}

export interface UserAddressRow {
  id: string;
  businessId: string;
  userId: string;
  receiverName: string;
  receiverPhone: string;
  province: string;
  city: string;
  district: string;
  detailAddress: string;
  fullAddress: string;
  tag?: 'home' | 'company' | 'school' | 'other' | string;
  isDefault?: boolean;
  createdAt?: string | Date;
  updatedAt?: string | Date;
}

export interface ProductSkuRow {
  id: string;
  businessId: string;
  productId: string;
  skuCode: string;
  specAttributes: Record<string, string | number>;
  price: number;
  costPrice?: number;
  stock: number;
  imageUrl?: string | null;
  status: 'active' | 'out_of_stock' | 'discontinued' | string;
  createdAt?: string | Date;
}

export interface LogisticsPackageRow {
  id: string;
  businessId: string;
  orderId: string;
  carrier: string;
  carrierCode: string;
  trackingNumber: string;
  status: 'pending_pickup' | 'in_transit' | 'delivering' | 'delivered' | 'exception' | 'rejected' | string;
  currentLocation?: string | null;
  courierName?: string | null;
  courierPhone?: string | null;
  estimatedDelivery?: string | Date | null;
  createdAt?: string | Date;
  updatedAt?: string | Date;
}

export interface LogisticsTrackRow {
  id: string;
  packageId: string;
  occurredAt: string | Date;
  location: string;
  status: 'picked_up' | 'transporting' | 'dispatching' | 'signed' | 'problem' | string;
  description: string;
  createdAt?: string | Date;
}

export interface ProductReviewRow {
  id: string;
  businessId: string;
  productId: string;
  skuId?: string | null;
  orderId?: string | null;
  userId: string;
  userName?: string | null;
  userAvatar?: string | null;
  rating: number;
  content: string;
  images?: string[] | null;
  fitFeedback?: 'true_to_size' | 'runs_small' | 'runs_large' | string | null;
  sentiment?: 'positive' | 'neutral' | 'negative' | string;
  merchantReply?: string | null;
  createdAt?: string | Date;
}

export interface AfterSaleTicketRow {
  id: string;
  businessId: string;
  orderId: string;
  orderItemId?: string | null;
  userId: string;
  type: 'refund_only' | 'return_and_refund' | 'exchange' | string;
  reason: 'wrong_size' | 'quality_issue' | 'not_as_described' | 'no_reason_7d' | string;
  reasonDescription?: string | null;
  refundAmount: number;
  status:
    | 'pending_review'
    | 'approved'
    | 'rejected'
    | 'waiting_user_ship'
    | 'merchant_inspecting'
    | 'completed'
    | 'cancelled'
    | string;
  returnTrackingNumber?: string | null;
  humanApprovalId?: string | null;
  createdAt?: string | Date;
  updatedAt?: string | Date;
}

export interface AfterSaleLogRow {
  id: string;
  ticketId: string;
  action: 'created' | 'approved' | 'rejected' | 'shipped_back' | 'refunded' | string;
  operator: string;
  note?: string | null;
  createdAt?: string | Date;
}
