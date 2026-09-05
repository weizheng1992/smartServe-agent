export interface RouteGreetingContext {
  pathname: string;
  productTitle?: string;
  productCategory?: string;
  productPrice?: number;
  orderCount?: number;
  cartItemCount?: number;
  addressCount?: number;
}

/**
 * 根据当前商户路由和页面上下文返回针对性的智能问候语
 */
export function getGreetingForRoute(ctx: RouteGreetingContext): string {
  const { pathname, productTitle, productCategory, orderCount, cartItemCount, addressCount } = ctx;

  if (pathname.startsWith('/products/')) {
    if (productTitle) {
      return `您好！欢迎浏览「${productTitle}」✨ 这是我们的${productCategory ? `热销${productCategory}类目商品` : '精选好物'}。如果您对材质参数、尺码选择或库存优惠有疑问，随时问我哦！`;
    }
    return '您好！欢迎查看商品详情。如果您对当前商品的规格尺码、洗涤保养或库存有疑问，我可以为您实时解答！';
  }

  if (pathname === '/cart') {
    if (cartItemCount && cartItemCount > 0) {
      return `您好！检测到您购物车中有 ${cartItemCount} 件心仪商品。需要我帮您核对满减优惠券、库存状态或收货地址吗？`;
    }
    return '您好！您的购物车空空如也，需要我为您推荐当季机能穿搭新品或热销榜单吗？';
  }

  if (pathname === '/orders') {
    if (orderCount && orderCount > 0) {
      return `您好！您目前有 ${orderCount} 笔订单记录。如果您需要查询实时顺丰物流、申请退款退货，或者修改未发货订单的配送地址，请直接告诉我订单号！`;
    }
    return '您好！这是您的订单中心。您可以在此查看历史消费流水、跟踪包裹轨迹，或发起售后与退款咨询。';
  }

  if (pathname === '/addresses') {
    if (addressCount && addressCount > 0) {
      return `您好！这是您的常用收货地址簿（共 ${addressCount} 个地址）。如果需要将未发货订单一键同步更新到新地址，我可以协助您办理！`;
    }
    return '您好！欢迎管理收货地址簿。建议您添加并设置默认收货地址，下单与修改地址将更加便捷！';
  }

  // 默认首页
  return '您好！我是极光潮品官方智能客服。请问有什么可以帮您？支持多订单查询、极速修改收货地址、售后退换货与物流进度追踪。';
}
