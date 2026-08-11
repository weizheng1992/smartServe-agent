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
  name?: string;
  description?: string;
  [key: string]: unknown;
}

export interface DatabaseProductRow {
  id?: string;
  name?: string;
  description?: string;
  price?: number;
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
