// 工作台数据形态(供各 tab 组件与 workbench hook 共用;此前内联在 504 行
// 的 workbench.tsx 里,按功能拆分后独立成模块)。
// 线上数据形态(DTO)真源在 lib/api.ts(2026-09-26 夜审 ⑤#3 收口:严禁页面
// 裸 fetch 后,类型随方法同源);此处再导出保持既有 import 路径不变。

export type { OrderRow, AuditLogRow, ApprovalItem, ConversationItem, MessageItem } from '@/lib/api';

export interface SkuRow {
  id: string;
  sku_code: string;
  sku_title: string;
  spu_title: string;
  brand: string;
  category: string;
  spec_attributes: Record<string, string>;
  price: number;
  original_price?: number;
  stock: number;
}

export interface SpuRow {
  id: string;
  spu_code: string;
  title: string;
  subtitle: string;
  category: string;
  brand: string;
  main_image: string;
  spec_dimensions: Array<{ name: string; values: string[] }>;
  specs: Record<string, string>;
}

export type WorkbenchTab = 'orders' | 'approvals' | 'live_desk' | 'spus' | 'skus' | 'spi_logs';
