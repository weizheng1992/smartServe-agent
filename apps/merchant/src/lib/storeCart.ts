import type { ThirdPartyProduct, ThirdPartySku } from 'types';

// 商户商城购物车的单一形状所有者(2026-09-14 NaN 事故收口)。
//
// 事故:localStorage `aurora_store_cart` 曾有三个写入方两种形状 —— 商城列表
// 弹窗与商品详情页写嵌套 {product, sku, quantity, selected},聊天悬浮窗写
// 扁平条目;而 CartPage 直接把存档断言成扁平 CartItem[](CartDrawer 契约),
// 嵌套条目取 item.price 得 undefined,Number(undefined)=NaN → 购物车页
// 「¥NaN」,且 skuCode/title/stock 全丢、结算载荷 skuCode=undefined。
// 收口:读写一律走本模块 —— 写入方产扁平形状,读取侧归一旧嵌套条目
// (用户浏览器里已中毒的存档无感自愈,无需清缓存)。

export const STORE_CART_STORAGE_KEY = 'aurora_store_cart';

export interface StoreCartItem {
  id: string; // = skuCode
  spuId: string; // 商品路由 id(/products/:id),取 SPU 编码(product.productId)
  skuCode: string;
  title: string;
  skuTitle: string;
  imageUrl: string;
  price: number;
  quantity: number;
  stock: number;
  specAttributes: Record<string, string>;
  selected: boolean;
}

// 兼容两种历史形状:扁平条目原样归一;嵌套 {product, sku} 条目拆包提平。
// 无法提取 skuCode 的残缺条目丢弃(无主数据在购物车里没有可操作性)。
export function normalizeStoreCartItem(raw: unknown): StoreCartItem | null {
  if (!raw || typeof raw !== 'object') return null;
  const item = raw as Record<string, any>;
  const product = (item.product || {}) as Record<string, any>;
  const sku = (item.sku || {}) as Record<string, any>;
  const skuCode: string | undefined = item.skuCode || sku.skuCode;
  if (!skuCode) return null;
  const price = Number(item.price ?? sku.price ?? product.price ?? 0);
  return {
    id: item.id || skuCode,
    spuId: item.spuId || product.spuId || product.productId || product.id || '',
    skuCode,
    title: item.title || product.title || sku.skuTitle || '',
    skuTitle: item.skuTitle || sku.skuTitle || '',
    imageUrl: item.imageUrl || sku.imageUrl || product.imageUrl || '',
    price: Number.isFinite(price) ? price : 0,
    quantity: Math.max(1, Number(item.quantity) || 1),
    stock: Number(item.stock ?? sku.stock ?? 0) || 0,
    specAttributes: item.specAttributes || sku.specAttributes || {},
    selected: item.selected !== false,
  };
}

export function readStoreCart(): StoreCartItem[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_CART_STORAGE_KEY) || '[]');
    if (!Array.isArray(raw)) return [];
    return raw.map(normalizeStoreCartItem).filter((it): it is StoreCartItem => it !== null);
  } catch {
    return [];
  }
}

export function writeStoreCart(items: StoreCartItem[]): void {
  localStorage.setItem(STORE_CART_STORAGE_KEY, JSON.stringify(items));
  // 与聊天悬浮窗同步路径同族:写入后广播,头部角标等监听方即时刷新
  window.dispatchEvent(new Event('cart_updated'));
  window.dispatchEvent(new Event('storage'));
}

// UI 加购统一入口(商城弹窗/商品详情页共用):同 SKU 累加数量,新条目产扁平形状
export function addStoreCartItem(product: ThirdPartyProduct, sku: ThirdPartySku, quantity: number): StoreCartItem[] {
  const cart = readStoreCart();
  const idx = cart.findIndex((it) => it.skuCode === sku.skuCode);
  if (idx >= 0) {
    cart[idx].quantity += quantity;
  } else {
    cart.push({
      id: sku.skuCode,
      spuId: product.productId || product.spuId || '',
      skuCode: sku.skuCode,
      title: product.title,
      skuTitle: sku.skuTitle,
      imageUrl: sku.imageUrl || product.imageUrl || '',
      price: Number(sku.price),
      quantity,
      stock: sku.stock ?? 0,
      specAttributes: sku.specAttributes || {},
      selected: true,
    });
  }
  writeStoreCart(cart);
  return cart;
}
