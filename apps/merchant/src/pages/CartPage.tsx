import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Button } from 'ui';
import { AddressModal, type CustomerAddress } from '../components/address/AddressModal';
import type { CartItem } from '../components/cart/CartDrawer';
import { StorefrontHeader } from '../components/navbar/StorefrontHeader';
import { useCurrentUser } from '../context/UserContext';
import { readStoreCart, writeStoreCart } from '../lib/storeCart';

export default function CartPage() {
  const navigate = useNavigate();
  const { user } = useCurrentUser();
  // 选券重构(2026-09-22):券由用户自选,不再「结算自动抵扣」。
  // preview 为服务端只读试算(原价/活动/券包逐张可用性),金额口径与下单一致
  const [preview, setPreview] = useState<{
    originalAmount: number;
    totalQuantity: number;
    activity: { name: string; discount: number } | null;
    coupons: Array<{ couponId: string; name: string; value: number; usable: boolean; discount: number }>;
    bestCouponId: string | null;
  } | null>(null);
  // 'none'=明确不用券;具体 id=自选券(与活动叠加:活动先减,券按余额抵扣)
  const [selectedCouponId, setSelectedCouponId] = useState<string>('none');
  const [cart, setCart] = useState<CartItem[]>([]);
  const [addresses, setAddresses] = useState<CustomerAddress[]>([]);
  const [selectedAddress, setSelectedAddress] = useState<CustomerAddress | null>(null);
  const [isAddressModalOpen, setIsAddressModalOpen] = useState(false);
  const [isCheckingOut, setIsCheckingOut] = useState(false);
  const [checkoutResult, setCheckoutResult] = useState<{
    orderId?: string;
    message?: string;
  } | null>(null);

  // 加载购物车和地址数据
  useEffect(() => {
    // 经单一所有者归一读取(2026-09-14 NaN 事故):历史嵌套 {product, sku} 条目
    // 在读取侧提平自愈,已中毒的本地存档无需清缓存
    setCart(readStoreCart());

    const fetchAddresses = async () => {
      try {
        const res = await fetch('/api/store/addresses');
        const data = await res.json();
        if (data.success && data.addresses) {
          setAddresses(data.addresses);
          const defaultAddr = data.addresses.find((a: CustomerAddress) => a.isDefault) || data.addresses[0];
          setSelectedAddress(defaultAddr || null);
        }
      } catch {
        // ignore
      }
    };
    fetchAddresses();
  }, []);

  // 引擎车合流(2026-09-15 单账本收口):聊天侧入车在引擎账本(Redis),本地
  // 存档只是缓存 —— 聊天加购后商城页永远少一件,且回复瞬间的前端卡片同步一
  // 错过(导航/刷新打断)就永久不同步。挂载时拉引擎车行合流:引擎行权威
  // (含点名直配的 skuCode/规格),本地独有行(商城页加购,尚未随消息水合)
  // 保留,合流结果回写存档。
  useEffect(() => {
    if (!user.id) return;
    const fetchEngineCart = async () => {
      try {
        const res = await fetch(`/api/store/cart?customerId=${encodeURIComponent(user.id)}`);
        const data = await res.json();
        if (!data.success || !Array.isArray(data.items) || data.items.length === 0) return;
        const engineRows: CartItem[] = data.items.map((r: any) => ({
          id: r.skuCode || r.skuId,
          spuId: r.spuId || r.skuId,
          skuCode: r.skuCode || r.skuId,
          title: r.title,
          skuTitle: r.specSummary || (r.spec ? Object.values(r.spec).join(' / ') : ''),
          imageUrl: r.imageUrl || '',
          price: Number(r.price) || 0,
          quantity: Math.max(1, Number(r.quantity) || 1),
          stock: 99,
          specAttributes: r.spec || {},
          selected: true,
        }));
        setCart((prev) => {
          // 合流去重键:引擎行的 skuCode(确切规格)与 spuId(SPU 回指);
          // 本地行任一键命中即视为同一商品(引擎行权威,数量以引擎为准)
          const engineKeys = new Set(engineRows.flatMap((r) => [r.skuCode, r.spuId, r.id]));
          const localOnly = prev.filter(
            (it) => !engineKeys.has(it.skuCode) && !engineKeys.has(it.spuId) && !engineKeys.has(it.id),
          );
          const merged = [...engineRows, ...localOnly];
          writeStoreCart(merged as any);
          return merged;
        });
      } catch {
        // 引擎车不可达:本地存档照常展示(降级不炸页面)
      }
    };
    fetchEngineCart();
  }, [user.id]);

  const saveCart = (newCart: CartItem[]) => {
    setCart(newCart);
    writeStoreCart(newCart);
  };

  const handleUpdateQuantity = (skuCode: string, delta: number) => {
    const updated = cart.map((item) => {
      if (item.skuCode === skuCode) {
        const newQty = Math.max(1, Math.min(item.stock, item.quantity + delta));
        return { ...item, quantity: newQty };
      }
      return item;
    });
    saveCart(updated);
  };

  const handleToggleSelect = (skuCode: string) => {
    const updated = cart.map((item) => (item.skuCode === skuCode ? { ...item, selected: !item.selected } : item));
    saveCart(updated);
  };

  const handleToggleSelectAll = () => {
    const allSelected = cart.every((it) => it.selected);
    const updated = cart.map((it) => ({ ...it, selected: !allSelected }));
    saveCart(updated);
  };

  const handleRemoveItem = (skuCode: string) => {
    const updated = cart.filter((item) => item.skuCode !== skuCode);
    saveCart(updated);
  };

  const handleClearCart = () => {
    saveCart([]);
  };

  const selectedItems = cart.filter((it) => it.selected);
  const totalPrice = selectedItems.reduce((sum, it) => sum + Number(it.price) * it.quantity, 0);
  const totalCount = selectedItems.reduce((sum, it) => sum + it.quantity, 0);

  // 试算随选中项变化重拉(cartKey 收敛依赖:同商品同数量不重复请求);
  // 券包/活动随金额口径联动,试算失败静默降级为原价展示,不阻断购物车
  const selectedKey = selectedItems.map((it) => `${it.skuCode}:${it.quantity}`).join('|');
  useEffect(() => {
    const items = selectedItems;
    if (!user.id || items.length === 0) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/store/checkout/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            customerId: user.id,
            items: items.map((it) => ({ skuCode: it.skuCode, quantity: it.quantity })),
          }),
        });
        const data = await res.json();
        if (!cancelled && data.success) setPreview(data);
      } catch {
        // 试算不可达:保持原价明细,选券面板为空
        if (!cancelled) setPreview(null);
      }
    })();
    return () => {
      cancelled = true;
    };
    // biome-ignore lint/correctness/useExhaustiveDependencies: selectedItems 由 cartKey 派生,拆行重算无意义
  }, [user.id, selectedKey]);

  // 购物车变化后所选券失效(已核销/不再可用)→ 诚实回落「不使用」
  useEffect(() => {
    if (selectedCouponId !== 'none' && preview && !preview.coupons.some((c) => c.couponId === selectedCouponId)) {
      setSelectedCouponId('none');
    }
  }, [preview, selectedCouponId]);

  // 明细口径与后端 _resolve_promotion 一致(2026-09-22 叠加决议):
  // 活动自动必享,券自选叠加 —— 活动先减,券按余额抵扣(试算已按余额算好)
  const activity = preview?.activity ?? null;
  const selectedCoupon = preview?.coupons.find((c) => c.couponId === selectedCouponId) ?? null;
  const couponDiscount = selectedCoupon ? Number(selectedCoupon.discount) : 0;
  const activityDiscount = activity ? Number(activity.discount) : 0;
  const originalAmount = preview ? Number(preview.originalAmount) : totalPrice;
  const payableAmount = Math.max(0, originalAmount - couponDiscount - activityDiscount);
  const totalSaved = couponDiscount + activityDiscount;

  const handleCheckout = async () => {
    if (selectedItems.length === 0 || !selectedAddress) return;
    setIsCheckingOut(true);

    try {
      // 整单一次结算(2026-09-22 重构):单订单 + 服务端按整单金额判优惠,
      // 替代旧的逐商品下单 —— 旧口径下多件商品会静默烧掉多张券,且满减
      // 阈值按单件金额判,整单够门槛却不生效
      const res = await fetch('/api/store/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customerId: user.id,
          items: selectedItems.map((it) => ({ skuCode: it.skuCode, quantity: it.quantity })),
          shippingAddress: {
            recipientName: selectedAddress.recipientName || user.name,
            phone: selectedAddress.phone || user.phone,
            fullAddress: selectedAddress.fullAddress,
          },
          couponId: selectedCouponId,
        }),
      });
      const data = await res.json();
      if (data.success && data.orderId) {
        // 结算完成后从购物车剔除选中的项;所选券已核销,回落「不使用」
        saveCart(cart.filter((it) => !it.selected));
        setSelectedCouponId('none');
        const savedNote =
          Number(data.discount) > 0 ? `共优惠 ¥${Number(data.discount).toFixed(2)}（${data.promoName}）。` : '';
        setCheckoutResult({
          orderId: data.orderId,
          message: `结算成功！订单 ${data.orderId} 实付 ¥${Number(data.payableAmount).toFixed(2)}。${savedNote}`,
        });
      } else {
        alert(data.message || '下单失败，请重试');
      }
    } catch {
      alert('下单结算出现异常，请重试');
    } finally {
      setIsCheckingOut(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <StorefrontHeader cartCount={cart.reduce((s, i) => s + i.quantity, 0)} />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 flex items-center space-x-2">
            <span>🛒 购物车</span>
            <span className="text-xs font-normal text-slate-500">({cart.length} 款商品)</span>
          </h1>
          {cart.length > 0 && (
            <button
              type="button"
              onClick={handleClearCart}
              className="text-xs text-rose-600 hover:text-rose-700 font-medium cursor-pointer"
            >
              清空购物车
            </button>
          )}
        </div>

        {checkoutResult && (
          <div className="mb-6 p-4 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-2xl flex items-center justify-between">
            <div>
              <div className="font-bold text-sm">🎉 {checkoutResult.message}</div>
              <div className="text-xs text-emerald-600 mt-0.5">
                智能客服已为您同步该订单信息，可随时咨询物流或申请改单！
              </div>
            </div>
            <Link
              to="/orders"
              className="px-3 py-1.5 bg-emerald-600 text-white rounded-lg text-xs font-semibold hover:bg-emerald-500 transition"
            >
              前往我的订单 →
            </Link>
          </div>
        )}

        {cart.length === 0 ? (
          <div className="bg-white rounded-2xl p-12 border border-slate-200 text-center max-w-xl mx-auto my-8">
            <div className="text-5xl mb-3">🛒</div>
            <h2 className="text-base font-bold text-slate-800">购物车空空如也</h2>
            <p className="text-xs text-slate-400 mt-1">快去挑选心仪的机能服饰与配件吧！</p>
            <div className="mt-6">
              <Link
                to="/"
                className="px-5 py-2.5 bg-emerald-600 text-white text-xs font-semibold rounded-xl hover:bg-emerald-500 shadow-xs transition"
              >
                前往选购
              </Link>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
            {/* 左侧商品列表 */}
            <div className="lg:col-span-8 space-y-4">
              <div className="bg-white rounded-2xl p-4 border border-slate-200 flex items-center justify-between">
                <label className="flex items-center space-x-2 text-xs font-bold text-slate-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={cart.length > 0 && cart.every((it) => it.selected)}
                    onChange={handleToggleSelectAll}
                    className="w-4 h-4 text-emerald-600 rounded"
                  />
                  <span>全选所有商品</span>
                </label>
                <span className="text-xs text-slate-400">已选 {totalCount} 件商品</span>
              </div>

              <div className="space-y-3">
                {cart.map((item) => (
                  <div
                    key={item.skuCode}
                    className="bg-white rounded-2xl p-4 border border-slate-200 shadow-2xs flex items-center space-x-4"
                  >
                    <input
                      type="checkbox"
                      checked={item.selected}
                      onChange={() => handleToggleSelect(item.skuCode)}
                      className="w-4 h-4 text-emerald-600 rounded shrink-0 cursor-pointer"
                    />
                    {item.imageUrl ? (
                      <img
                        src={item.imageUrl}
                        alt={item.title}
                        className="w-20 h-20 rounded-xl object-cover border border-slate-200 shrink-0"
                      />
                    ) : (
                      <div className="w-20 h-20 rounded-xl bg-slate-100 border border-slate-200 shrink-0 flex items-center justify-center text-xl">
                        🛍️
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <Link
                        to={`/products/${item.spuId}`}
                        className="text-xs font-bold text-slate-900 hover:text-emerald-700 truncate block"
                      >
                        {item.title}
                      </Link>
                      <div className="text-[11px] text-slate-500 mt-0.5">规格: {item.skuTitle}</div>
                      <div className="text-emerald-700 font-extrabold text-sm mt-1">
                        ¥{Number(item.price).toFixed(2)}
                      </div>
                    </div>

                    {/* 数量加减 */}
                    <div className="flex items-center border border-slate-200 rounded-lg overflow-hidden bg-white shrink-0">
                      <button
                        type="button"
                        onClick={() => handleUpdateQuantity(item.skuCode, -1)}
                        disabled={item.quantity <= 1}
                        className="px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-30"
                      >
                        -
                      </button>
                      <span className="px-2.5 py-1 text-xs font-bold text-slate-800 min-w-6 text-center">
                        {item.quantity}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleUpdateQuantity(item.skuCode, 1)}
                        disabled={item.quantity >= item.stock}
                        className="px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-30"
                      >
                        +
                      </button>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleRemoveItem(item.skuCode)}
                      className="text-slate-400 hover:text-rose-600 text-xs p-1 cursor-pointer shrink-0"
                    >
                      🗑️
                    </button>
                  </div>
                ))}
              </div>
            </div>

            {/* 右侧结算卡片 */}
            <div className="lg:col-span-4 space-y-4">
              {/* 配送地址选择卡片 */}
              <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-2xs space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-800">📍 配送收货地址</span>
                  <button
                    type="button"
                    onClick={() => setIsAddressModalOpen(true)}
                    className="text-xs text-emerald-700 font-semibold hover:underline cursor-pointer"
                  >
                    切换地址
                  </button>
                </div>
                {selectedAddress ? (
                  <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 text-xs space-y-1">
                    <div className="font-bold text-slate-900">
                      {selectedAddress.recipientName}{' '}
                      <span className="font-normal text-slate-500 font-mono">{selectedAddress.phone}</span>
                    </div>
                    <div className="text-slate-600 leading-relaxed">{selectedAddress.fullAddress}</div>
                  </div>
                ) : (
                  <div className="text-xs text-slate-400">暂无选中的配送地址</div>
                )}
              </div>

              {/* 优惠券选择卡片(选券重构 2026-09-22):数据来自服务端试算, */}
              {/* 只列可用张;满减/折扣活动与优惠券叠加,活动先减、券按余额 */}
              <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-2xs space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-800">🎫 优惠券</span>
                  {preview && preview.coupons.length > 0 && (
                    <span className="text-[11px] font-medium text-rose-600">{preview.coupons.length} 张可用</span>
                  )}
                </div>
                {!preview || preview.coupons.length === 0 ? (
                  <div className="text-xs text-slate-400">暂无可用优惠券，去商品页领券吧～</div>
                ) : (
                  <div className="space-y-2">
                    <label className="flex items-center space-x-2 cursor-pointer">
                      <input
                        type="radio"
                        name="coupon"
                        checked={selectedCouponId === 'none'}
                        onChange={() => setSelectedCouponId('none')}
                        className="w-3.5 h-3.5 accent-slate-600 cursor-pointer"
                      />
                      <span className="text-xs text-slate-700">不使用优惠券</span>
                    </label>
                    {preview.coupons.map((c) => (
                      <label
                        key={c.couponId}
                        className={`flex items-center justify-between rounded-xl border px-3 py-2 cursor-pointer transition ${
                          selectedCouponId === c.couponId
                            ? 'border-rose-300 bg-rose-50/70'
                            : 'border-dashed border-rose-200 bg-white hover:bg-rose-50/40'
                        }`}
                      >
                        <span className="flex items-center space-x-2 min-w-0">
                          <input
                            type="radio"
                            name="coupon"
                            checked={selectedCouponId === c.couponId}
                            onChange={() => setSelectedCouponId(c.couponId)}
                            className="w-3.5 h-3.5 accent-rose-600 shrink-0 cursor-pointer"
                          />
                          <span className="text-xs font-semibold text-slate-800 truncate">
                            ¥{Number(c.value).toFixed(2)} · {c.name}
                          </span>
                          {c.couponId === preview.bestCouponId && (
                            <span className="shrink-0 rounded-full bg-rose-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                              最优惠
                            </span>
                          )}
                        </span>
                        <span className="shrink-0 text-xs font-bold text-rose-600">
                          抵 ¥{Number(c.discount).toFixed(2)}
                        </span>
                      </label>
                    ))}
                    {activity && (
                      <div className="text-[11px] leading-relaxed text-slate-400">
                        「{activity.name}」活动优惠可与优惠券叠加：活动先减，优惠券按活动后余额抵扣。
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* 费用与结算按钮 */}
              <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-2xs space-y-4">
                <div className="space-y-2 text-xs">
                  <div className="flex justify-between text-slate-600">
                    <span>商品原价 ({totalCount} 件)</span>
                    <span>¥{originalAmount.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between text-slate-600">
                    <span>顺丰特快运费</span>
                    <span className="text-emerald-700 font-medium">免运费</span>
                  </div>
                  {activityDiscount > 0 && (
                    <div className="flex justify-between font-medium text-rose-600">
                      <span>活动优惠（{activity?.name}）</span>
                      <span>-¥{activityDiscount.toFixed(2)}</span>
                    </div>
                  )}
                  {couponDiscount > 0 && (
                    <div className="flex justify-between font-medium text-rose-600">
                      <span>优惠券抵扣（{selectedCoupon?.name}）</span>
                      <span>-¥{couponDiscount.toFixed(2)}</span>
                    </div>
                  )}
                  {totalSaved > 0 && (
                    <div className="flex justify-between font-semibold text-rose-600">
                      <span>合计已优惠</span>
                      <span>-¥{totalSaved.toFixed(2)}</span>
                    </div>
                  )}
                  <div className="border-t border-slate-100 pt-2 flex justify-between items-baseline">
                    <span className="font-bold text-slate-900">实付总金额</span>
                    <span className="text-xl font-extrabold text-emerald-700">¥{payableAmount.toFixed(2)}</span>
                  </div>
                </div>

                <Button
                  type="button"
                  onClick={handleCheckout}
                  disabled={selectedItems.length === 0 || !selectedAddress || isCheckingOut}
                  className="w-full py-5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-xs"
                >
                  {isCheckingOut ? '正在提交结算...' : `⚡ 立即结算 (${totalCount} 件)`}
                </Button>
              </div>
            </div>
          </div>
        )}
      </main>

      <AddressModal
        isOpen={isAddressModalOpen}
        onClose={() => setIsAddressModalOpen(false)}
        addresses={addresses}
        selectedAddressId={selectedAddress?.id}
        onSelectAddress={(addr) => setSelectedAddress(addr)}
        onAddAddress={async (newAddr) => {
          try {
            const res = await fetch('/api/store/addresses', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                customerId: user.id || 'CUST-8801',
                ...newAddr,
              }),
            });
            const data = await res.json();
            if (data.success && data.address) {
              setAddresses((prev) => [data.address, ...prev]);
              setSelectedAddress(data.address);
            }
          } catch {
            // ignore
          }
        }}
      />
    </div>
  );
}
