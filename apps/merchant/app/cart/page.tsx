'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import React, { useEffect, useState } from 'react';
import { Button } from 'ui';
import { AddressModal, type CustomerAddress } from '../components/address/AddressModal';
import type { CartItem } from '../components/cart/CartDrawer';
import { StorefrontHeader } from '../components/navbar/StorefrontHeader';
import { useCurrentUser } from '../context/UserContext';

export default function CartPage() {
  const router = useRouter();
  const { user } = useCurrentUser();
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
    try {
      const stored = localStorage.getItem('aurora_store_cart');
      if (stored) {
        setCart(JSON.parse(stored));
      }
    } catch {
      // ignore
    }

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

  const saveCart = (newCart: CartItem[]) => {
    setCart(newCart);
    localStorage.setItem('aurora_store_cart', JSON.stringify(newCart));
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

  const handleCheckout = async () => {
    if (selectedItems.length === 0 || !selectedAddress) return;
    setIsCheckingOut(true);

    try {
      // 循环结算选中的商品项
      const orderIds: string[] = [];
      for (const item of selectedItems) {
        const res = await fetch('/api/store/orders', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            customerId: user.id,
            skuCode: item.skuCode,
            quantity: item.quantity,
            shippingAddress: selectedAddress.fullAddress,
            recipientName: selectedAddress.recipientName || user.name,
            recipientPhone: selectedAddress.phone || user.phone,
          }),
        });
        const data = await res.json();
        if (data.success && data.orderId) {
          orderIds.push(data.orderId);
        }
      }

      // 结算完成后从购物车剔除选中的项
      const remainCart = cart.filter((it) => !it.selected);
      saveCart(remainCart);

      setCheckoutResult({
        orderId: orderIds.join(', '),
        message: `结算成功！已生成订单：${orderIds.join(', ')}`,
      });
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
              href="/orders"
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
                href="/"
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
                    <img
                      src={item.imageUrl}
                      alt={item.title}
                      className="w-20 h-20 rounded-xl object-cover border border-slate-200 shrink-0"
                    />
                    <div className="flex-1 min-w-0">
                      <Link
                        href={`/products/${item.spuId}`}
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

              {/* 费用与结算按钮 */}
              <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-2xs space-y-4">
                <div className="space-y-2 text-xs">
                  <div className="flex justify-between text-slate-600">
                    <span>商品总计 ({totalCount} 件)</span>
                    <span>¥{totalPrice.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between text-slate-600">
                    <span>顺丰特快运费</span>
                    <span className="text-emerald-700 font-medium">免运费</span>
                  </div>
                  <div className="border-t border-slate-100 pt-2 flex justify-between items-baseline">
                    <span className="font-bold text-slate-900">实付总金额</span>
                    <span className="text-xl font-extrabold text-emerald-700">¥{totalPrice.toFixed(2)}</span>
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
