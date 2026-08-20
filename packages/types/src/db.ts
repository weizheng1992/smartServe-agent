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

export interface TenantRow {
  id: string;
  businessId: string;
  name: string;
  planTier: "free" | "pro" | "enterprise";
  status: "active" | "suspended";
  createdAt?: string | Date;
}

export interface TenantMemberRow {
  id: string;
  tenantId: string;
  userId: string;
  role: "owner" | "admin" | "agent";
  createdAt?: string | Date;
}

export interface TenantConfigRow {
  id: string;
  businessId: string;
  systemPrompt?: string | null;
  welcomeMessage?: string | null;
  temperature?: number | null;
  status: "draft" | "published";
  version: number;
  updatedAt?: string | Date;
}

export interface TenantToolRow {
  id: string;
  tenantId: string;
  name: string;
  description?: string | null;
  schema: Record<string, unknown>;
  authType: "none" | "bearer" | "basic" | "custom_header";
  encryptedCredentials?: string | null;
  requiresApproval: boolean;
  enabled: boolean;
  createdAt?: string | Date;
}
