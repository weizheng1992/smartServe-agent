// 工作台数据形态:DTO 真源在 lib/api.ts(2026-09-26 夜审 ⑤#3 收口:严禁页面
// 裸 fetch 后,类型随方法同源);此处再导出保持既有 import 路径不变。
// (候选⑤清理:SkuRow/SpuRow/WorkbenchTab 零消费死类型删除;merchant app 的
// 同名类型是其本地独立声明,与本文件无关。)

export type { OrderRow, AuditLogRow, ApprovalItem, ConversationItem, MessageItem } from '@/lib/api';
