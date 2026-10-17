// 租户身份单点(2026-10-17 审查收口):此前 'aurora' 字面量散落 FloatingChatWidget
// / MerchantAdminPage 等 6+ 处,换租户须全库扫字面量。Vite 只向客户端暴露 VITE_
// 前缀变量 —— 旧 .env.example 的 MERCHANT_ID 在 SPA 内不可达(实测 src 零引用),
// 正名 VITE_MERCHANT_ID,演示缺省 aurora(.env.example 同步)。
export const MERCHANT_ID: string = (() => {
  const raw = import.meta.env.VITE_MERCHANT_ID;
  return typeof raw === 'string' && raw.trim() ? raw.trim() : 'aurora';
})();

// 聊天线程/消息缓存键(用户+线程维度隔离)。注意:aurora_ 键面前缀是既有
// 浏览器存档命名空间 —— 改名即弃用户本地数据,刻意不收编进 MERCHANT_ID。
export const activeThreadKey = (userId: string): string => `aurora_active_thread_${userId}`;

export const chatMsgsKey = (userId: string, threadId: string): string => `aurora_chat_msgs_${userId}_${threadId}`;

// 本地新线程号布料(服务端线程 id 才是事实源;此布料仅用于无服务端会话时的
// 本地占位,旧布料线程 id 仍是不透明字符串照常可载入)
export const merchantThreadId = (userId: string): string => `merchant_thread_${userId}_${MERCHANT_ID}_${Date.now()}`;
