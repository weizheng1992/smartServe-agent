import type { ThirdPartyProduct, ThirdPartySku } from 'types';

// 商户商城购物车的单一形状所有者(2026-09-14 NaN 事故收口)。
//
// 事故:localStorage `aurora_store_cart` 曾有三个写入方两种形状 —— 商城列表
// 弹窗与商品详情页写嵌套 {product, sku, quantity, selected},聊天悬浮窗写
// 扁平条目;而 CartPage 直接把存档断言成扁平 CartItem[](CartDrawer 契约,
// 该组件已删,形状收编为本模块 StoreCartItem),
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
  /** null = 库存未知(聊天同步/引擎合流行不带库存,严禁编造兜底值) */
  stock: number | null;
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
  const stock = item.stock ?? sku.stock;
  return {
    id: item.id || skuCode,
    spuId: item.spuId || product.spuId || product.productId || product.id || '',
    skuCode,
    title: item.title || product.title || sku.skuTitle || '',
    skuTitle: item.skuTitle || sku.skuTitle || '',
    imageUrl: item.imageUrl || sku.imageUrl || product.imageUrl || '',
    price: Number.isFinite(price) ? price : 0,
    quantity: Math.max(1, Number(item.quantity) || 1),
    stock: typeof stock === 'number' && Number.isFinite(stock) ? stock : null,
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

// 聊天 cart_card 快照行(服务端宽松形状:skuCode/skuId/id 多键并存,字段皆可选)
export interface CartSnapshotItem {
  skuCode?: string;
  skuId?: string;
  id?: string;
  spuId?: string;
  title?: string;
  specSummary?: string;
  skuTitle?: string;
  imageUrl?: string;
  price?: number | string;
  quantity?: number | string;
}

// 聊天快照合并单点(2026-10-17 自 FloatingChatWidget.syncCartToLocalStorage 逐行搬入,
// Feature Envy 收口:widget 只识别卡片/清空并落盘,合并与对账语义归本模块所有)。
// 语义保持:多键命中覆盖不累加、specTitle/price/imageUrl 仅在有值时覆盖、快照对账剔除;
// 唯一行为变更是新增条目的伪造缺省改诚实(price 0 由车页 hasPrice 闸渲染「价格待确认」)。
export function mergeCartSnapshot(items: CartSnapshotItem[]): StoreCartItem[] {
  // 经单一所有者读写(2026-09-14 NaN 事故):读取侧归一历史嵌套条目
  const existingCart: any[] = readStoreCart();
  for (const item of items) {
    const skuCode = item.skuCode || item.skuId || item.id;
    if (!skuCode) continue;

    const idx = existingCart.findIndex((it: any) => (it.skuCode || it.sku?.skuCode || it.id) === skuCode);

    if (idx >= 0) {
      // 服务端 cart_card 的 items 是加购/改量后的全量快照(该 SKU 当前总数),
      // 一律覆盖而非累加——engine 侧已按 userId 维度累加,前端再累加会翻倍。
      // 标题/规格/价格同样以服务端快照为准:若只覆盖 quantity,localStorage 里
      // 陈旧占位标题(如历史演示数据)会在车页永久残留(2026-09-08 同步修复)。
      existingCart[idx].quantity = Number(item.quantity || 1);
      if (item.title) existingCart[idx].title = item.title;
      const specTitle = item.specSummary || item.skuTitle;
      if (specTitle) {
        existingCart[idx].skuTitle = specTitle;
        if (existingCart[idx].sku) existingCart[idx].sku.skuTitle = specTitle;
      }
      if (item.price !== undefined && item.price !== null) {
        existingCart[idx].price = Number(item.price);
        if (existingCart[idx].sku) existingCart[idx].sku.price = Number(item.price);
      }
      if (item.imageUrl) existingCart[idx].imageUrl = item.imageUrl;
    } else {
      existingCart.push({
        id: skuCode,
        spuId: item.spuId || '',
        skuCode: skuCode,
        title: item.title,
        skuTitle: item.specSummary || item.skuTitle || '',
        imageUrl: item.imageUrl || '',
        price: Number.isFinite(Number(item.price)) ? Number(item.price) : 0,
        // 钳制与 normalizeStoreCartItem 读侧同一法(负数量入档即 1,存档形态归一);
        // 对抗复核裁定:与所有者模块自身不变量对齐,非语义漂移(2026-10-17)
        quantity: Math.max(1, Number(item.quantity) || 1),
        // 聊天快照行不带库存,存 null(诚实未知);此前编造 99 会让 + 按钮帽与展示骗人
        stock: null,
        specAttributes: {},
        selected: true,
      });
    }
  }

  // 快照对账(2026-09-14):cart_card items 是引擎车的全量快照 —— 本地有而
  // 快照没有的条目即聊天侧已删除,不剔除则商城页删除永不生效。引擎车行是
  // SPU 粒度(skuId=spu 码),快照同时携带 skuCode(确切规格)与 spuId,
  // 本地条目任一键命中即视为仍在车。
  const snapshotIds = new Set<string>();
  for (const it of items) {
    for (const key of [it.skuCode, it.skuId, it.id, it.spuId]) {
      if (key) snapshotIds.add(String(key));
    }
  }
  const reconciled = existingCart.filter((it: any) => {
    const own = [it.skuCode, it.sku?.skuCode, it.id, it.spuId].filter(Boolean).map(String);
    return own.length === 0 || own.some((k) => snapshotIds.has(k));
  });
  existingCart.length = 0;
  existingCart.push(...reconciled);

  return existingCart;
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
      stock: sku.stock,
      specAttributes: sku.specAttributes || {},
      selected: true,
    });
  }
  writeStoreCart(cart);
  return cart;
}
