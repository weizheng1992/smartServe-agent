// 收货地址解析的单一所有者。此前同型 parseAddress 在 4 个订单面文件逐字节
// 重复(LogisticsModal/OrderDetailModal/OrderDetailPage/OrdersPage),且每份
// 兜底都编造「张伟 / 13800138000 / 北京市海淀区…」——任何缺地址的订单都会
// 被渲染成同一个人的同一地址(伪造兜底,2026-09-29 商户台评审 ⑤ 收口)。
// 诚实兜底:字段缺失即显占位,不替数据撒谎。

export interface ShippingAddressView {
  recipientName: string;
  phone: string;
  fullAddress: string;
}

const UNKNOWN: ShippingAddressView = {
  recipientName: '未知收件人',
  phone: '—',
  fullAddress: '暂无收货地址信息',
};

/** shippingAddress 在订单载荷里有三种历史形态:对象 / JSON 字符串 / 纯文本串 */
export function parseShippingAddress(addr: unknown): ShippingAddressView {
  if (!addr) return UNKNOWN;
  if (typeof addr === 'string') {
    try {
      const parsed = JSON.parse(addr) as Record<string, unknown>;
      if (parsed && typeof parsed === 'object') {
        return {
          recipientName: (parsed.recipientName as string) || UNKNOWN.recipientName,
          phone: (parsed.phone as string) || UNKNOWN.phone,
          fullAddress: (parsed.fullAddress as string) || addr,
        };
      }
    } catch {
      // 纯文本地址串
    }
    return { ...UNKNOWN, fullAddress: addr };
  }
  const obj = addr as Record<string, unknown>;
  return {
    recipientName: (obj.recipientName as string) || UNKNOWN.recipientName,
    phone: (obj.phone as string) || UNKNOWN.phone,
    fullAddress: (obj.fullAddress as string) || UNKNOWN.fullAddress,
  };
}
