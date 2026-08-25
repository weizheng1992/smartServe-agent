'use client';

import Link from 'next/link';
import React, { useEffect, useState } from 'react';
import type { ThirdPartyOrder, ThirdPartyProduct, ThirdPartySku } from 'types';
import { Badge, Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from 'ui';
import { StorefrontHeader } from './components/navbar/StorefrontHeader';
import { useCurrentUser } from './context/UserContext';

export default function StorefrontPage() {
  const { user } = useCurrentUser();
  const [products, setProducts] = useState<ThirdPartyProduct[]>([]);
  const [ordersCount, setOrdersCount] = useState(0);
  const [addressCount, setAddressCount] = useState(0);
  const [cartCount, setCartCount] = useState(0);
  const [loading, setLoading] = useState(true);

  // 选规格购买/加购弹窗
  const [buyingProduct, setBuyingProduct] = useState<ThirdPartyProduct | null>(null);
  const [selectedSku, setSelectedSku] = useState<ThirdPartySku | null>(null);
  const [selectedAttrs, setSelectedAttrs] = useState<Record<string, string>>({});
  const [buyQuantity, setBuyQuantity] = useState(1);
  const [showSpecsModal, setShowSpecsModal] = useState<ThirdPartyProduct | null>(null);
  const [isCheckingOut, setIsCheckingOut] = useState(false);
  const [cartSuccessNotice, setCartSuccessNotice] = useState<string | null>(null);

  // 获取商品列表
  const fetchProducts = async () => {
    try {
      setLoading(true);
      const prodRes = await fetch('/api/store/products');
      const prodJson = await prodRes.json();
      if (prodJson.success) setProducts(prodJson.products || []);
    } catch (err) {
      console.error('Failed to load products:', err);
    } finally {
      setLoading(false);
    }
  };

  // 统计角标数据
  const fetchCounts = async (targetUserId = user.id) => {
    try {
      // 购物车数量
      const storedCart = JSON.parse(localStorage.getItem('aurora_store_cart') || '[]');
      const totalCart = storedCart.reduce((sum: number, it: any) => sum + (it.quantity || 1), 0);
      setCartCount(totalCart);

      // 订单与地址数量
      const [ordRes, addrRes] = await Promise.all([
        fetch(`/api/store/orders?customerId=${targetUserId}`),
        fetch(`/api/store/addresses?customerId=${targetUserId}`),
      ]);
      const ordJson = await ordRes.json();
      const addrJson = await addrRes.json();
      if (ordJson.success && ordJson.orders) setOrdersCount(ordJson.orders.length);
      if (addrJson.success && addrJson.addresses) setAddressCount(addrJson.addresses.length);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    fetchProducts();
    fetchCounts(user.id);
  }, [user.id]);

  const handleOpenBuyModal = (product: ThirdPartyProduct) => {
    setBuyingProduct(product);
    setBuyQuantity(1);
    if (product.skus && product.skus.length > 0) {
      setSelectedSku(product.skus[0]);
      setSelectedAttrs(product.skus[0].specAttributes || {});
    }
  };

  const handleSelectAttr = (dimName: string, val: string) => {
    if (!buyingProduct) return;
    const nextAttrs = { ...selectedAttrs, [dimName]: val };
    setSelectedAttrs(nextAttrs);

    const matchedSku = buyingProduct.skus?.find((s) => {
      const attrs = s.specAttributes || {};
      return Object.entries(nextAttrs).every(([k, v]) => attrs[k] === v);
    });

    if (matchedSku) {
      setSelectedSku(matchedSku);
    }
  };

  const handleAddToCart = () => {
    if (!buyingProduct || !selectedSku) return;
    const existingCart = JSON.parse(localStorage.getItem('aurora_store_cart') || '[]');
    const idx = existingCart.findIndex((it: any) => it.sku.skuCode === selectedSku.skuCode);
    if (idx >= 0) {
      existingCart[idx].quantity += buyQuantity;
    } else {
      existingCart.push({
        product: buyingProduct,
        sku: selectedSku,
        quantity: buyQuantity,
        selected: true,
      });
    }
    localStorage.setItem('aurora_store_cart', JSON.stringify(existingCart));
    fetchCounts();
    setCartSuccessNotice(`已将「${selectedSku.skuTitle}」加入购物车！`);
    setTimeout(() => setCartSuccessNotice(null), 3000);
    setBuyingProduct(null);
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans">
      <StorefrontHeader cartCount={cartCount} ordersCount={ordersCount} addressCount={addressCount} />

      {/* 商城 Banner */}
      <section className="bg-gradient-to-r from-slate-900 via-slate-800 to-emerald-950 text-white py-10 px-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
          <div>
            <span className="text-xs bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2.5 py-1 rounded-full uppercase tracking-wider font-semibold">
              2026 SPU + SKU 多规格旗舰首发
            </span>
            <h1 className="text-3xl sm:text-4xl font-extrabold mt-3 tracking-tight">极简机能 · 严选面料与多维规格</h1>
            <p className="text-slate-300 text-sm mt-2 max-w-xl">
              全系采用独立商品 SPU 建模，提供详尽材质技术参数、多颜色尺码 SKU 矩阵与智能库存同步。全站配备路由感知 AI
              智能客服。
            </p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/orders"
              className="px-5 py-2.5 bg-emerald-600 text-white font-medium rounded-lg hover:bg-emerald-500 transition shadow-sm flex items-center space-x-2 text-sm"
            >
              <span>📋 订单中心</span>
            </Link>
          </div>
        </div>
      </section>

      {/* 提示通知条 */}
      {cartSuccessNotice && (
        <div className="max-w-7xl mx-auto px-4 mt-4 w-full">
          <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-semibold flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span>✅</span>
              <span>{cartSuccessNotice}</span>
            </div>
            <Link href="/cart" className="underline hover:text-emerald-950 font-bold">
              去购物车结算 →
            </Link>
          </div>
        </div>
      )}

      {/* SPU 商品网格大厅 */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-slate-900 flex items-center space-x-2">
            <span>🔥 旗舰精选 SPU 系列</span>
            <span className="text-xs bg-slate-200 text-slate-700 px-2 py-0.5 rounded-full font-normal">
              {products.length} 个 SPU 单元
            </span>
          </h2>
          <span className="text-xs text-slate-500">读写商户独立数据库 merchant_spus & merchant_skus</span>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {[1, 2, 3, 4].map((n) => (
              <div key={n} className="bg-white rounded-xl border border-slate-200 p-4 h-80 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {products.map((product) => (
              <div
                key={product.productId}
                className="bg-white rounded-xl border border-slate-200 overflow-hidden hover:shadow-md transition flex flex-col justify-between group"
              >
                <div className="p-4 flex-1 flex flex-col">
                  {/* SPU 主图 */}
                  <Link
                    href={`/products/${product.productId}`}
                    className="w-full h-44 bg-slate-100 rounded-lg overflow-hidden mb-3 relative flex items-center justify-center block"
                  >
                    {product.imageUrl ? (
                      <img
                        src={product.imageUrl}
                        alt={product.title}
                        className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
                      />
                    ) : (
                      <span className="text-4xl">🛍️</span>
                    )}
                    <span className="absolute top-2 left-2 bg-slate-900/80 text-white text-[10px] px-2 py-0.5 rounded backdrop-blur-xs">
                      {product.brand || 'AURORA'}
                    </span>
                  </Link>

                  <span className="text-[11px] uppercase tracking-wider text-emerald-600 font-semibold mb-1">
                    {product.category || '潮流单品'}
                  </span>
                  <Link
                    href={`/products/${product.productId}`}
                    className="font-bold text-slate-900 text-sm line-clamp-2 leading-snug hover:text-emerald-700 transition"
                  >
                    {product.title}
                  </Link>
                  {product.subtitle && (
                    <p className="text-[11px] text-slate-500 line-clamp-1 mt-1">{product.subtitle}</p>
                  )}

                  {/* 规格标签 */}
                  {product.specDimensions && product.specDimensions.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1">
                      {product.specDimensions.map((dim) => (
                        <span
                          key={dim.name}
                          className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded border border-slate-200"
                        >
                          {dim.name}: {dim.values.slice(0, 2).join('/')}
                          {dim.values.length > 2 && '...'}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="mt-auto pt-3 flex items-center justify-between">
                    <div>
                      <span className="text-[10px] text-slate-400">起售价</span>
                      <div className="text-lg font-extrabold text-emerald-600">¥{Number(product.price).toFixed(2)}</div>
                    </div>
                    <div className="text-right">
                      <span className="text-[10px] text-slate-400 block">总库存</span>
                      <span className="text-xs font-semibold text-slate-700 bg-slate-100 px-2 py-0.5 rounded">
                        {product.stock} 件
                      </span>
                    </div>
                  </div>
                </div>

                <div className="p-3 bg-slate-50 border-t border-slate-100 flex gap-2">
                  <Link
                    href={`/products/${product.productId}`}
                    className="flex-1 py-1.5 text-center bg-white border border-slate-300 text-slate-700 text-xs font-semibold rounded-lg hover:bg-slate-100 transition cursor-pointer"
                  >
                    详情与参数
                  </Link>
                  <button
                    type="button"
                    onClick={() => handleOpenBuyModal(product)}
                    className="flex-1 py-1.5 bg-slate-900 text-white text-xs font-semibold rounded-lg hover:bg-slate-800 transition shadow-xs cursor-pointer"
                  >
                    选规格购买
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* SPU / SKU 选规格购买与加购弹窗 */}
      <Dialog open={Boolean(buyingProduct)} onOpenChange={(open) => !open && setBuyingProduct(null)}>
        {buyingProduct && (
          <DialogContent className="max-w-lg p-6 max-h-[90vh] flex flex-col">
            <DialogHeader className="pb-3 border-b border-slate-100">
              <DialogTitle className="text-base font-bold text-slate-900">选择商品规格与数量</DialogTitle>
            </DialogHeader>

            <div className="py-2 space-y-4 flex-1 overflow-y-auto">
              <div className="bg-slate-50 p-3.5 rounded-xl flex items-center space-x-3.5 border border-slate-200">
                <img
                  src={
                    selectedSku?.imageUrl ||
                    buyingProduct.imageUrl ||
                    'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=200'
                  }
                  alt="SKU"
                  className="w-16 h-16 rounded-lg object-cover border border-slate-200 bg-white"
                />
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-slate-900 text-xs truncate">
                    {selectedSku?.skuTitle || buyingProduct.title}
                  </div>
                  <div className="text-emerald-700 font-extrabold text-lg mt-0.5">
                    ¥{selectedSku ? Number(selectedSku.price).toFixed(2) : Number(buyingProduct.price).toFixed(2)}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    SKU 编号:{' '}
                    <span className="font-mono font-medium text-slate-700">{selectedSku?.skuCode || '请选择规格'}</span>{' '}
                    · 剩余库存:{' '}
                    <strong className="text-emerald-600">{selectedSku?.stock ?? buyingProduct.stock}</strong> 件
                  </div>
                </div>
              </div>

              {buyingProduct.specDimensions?.map((dim) => (
                <div key={dim.name} className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-700">{dim.name}</label>
                  <div className="flex flex-wrap gap-2">
                    {dim.values.map((val) => {
                      const isSelected = selectedAttrs[dim.name] === val;
                      return (
                        <button
                          key={val}
                          type="button"
                          onClick={() => handleSelectAttr(dim.name, val)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition cursor-pointer ${
                            isSelected
                              ? 'bg-emerald-600 text-white border-emerald-600 shadow-xs'
                              : 'bg-white text-slate-700 border-slate-200 hover:border-slate-400'
                          }`}
                        >
                          {val}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}

              <div className="flex items-center justify-between pt-2 border-t border-slate-100">
                <span className="text-xs font-bold text-slate-700">购买数量</span>
                <div className="flex items-center border border-slate-200 rounded-lg overflow-hidden bg-white shadow-2xs">
                  <button
                    type="button"
                    onClick={() => setBuyQuantity((q) => Math.max(1, q - 1))}
                    disabled={buyQuantity <= 1}
                    className="px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-30"
                  >
                    -
                  </button>
                  <span className="px-3 py-1 text-xs font-bold text-slate-800 min-w-8 text-center">{buyQuantity}</span>
                  <button
                    type="button"
                    onClick={() => setBuyQuantity((q) => Math.min(selectedSku?.stock ?? buyingProduct.stock, q + 1))}
                    disabled={buyQuantity >= (selectedSku?.stock ?? buyingProduct.stock)}
                    className="px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-30"
                  >
                    +
                  </button>
                </div>
              </div>
            </div>

            <DialogFooter className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setBuyingProduct(null)}
                className="text-xs"
              >
                取消
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={handleAddToCart}
                disabled={!selectedSku || selectedSku.stock <= 0}
                className="bg-amber-500 hover:bg-amber-400 text-white text-xs font-bold shadow-xs"
              >
                🛒 加入购物车
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </div>
  );
}
