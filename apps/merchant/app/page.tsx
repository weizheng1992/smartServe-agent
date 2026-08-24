'use client';

import React, { useEffect, useState } from 'react';
import type { ThirdPartyOrder, ThirdPartyProduct, ThirdPartySku } from 'types';
import { Badge, Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input } from 'ui';
import { AddressModal, type CustomerAddress } from './components/address/AddressModal';
import { CartDrawer, type CartItem } from './components/cart/CartDrawer';
import { LogisticsModal } from './components/orders/LogisticsModal';
import { OrderDetailModal } from './components/orders/OrderDetailModal';
import { OrdersListModal } from './components/orders/OrdersListModal';

export default function StorefrontPage() {
  // 数据源
  const [products, setProducts] = useState<ThirdPartyProduct[]>([]);
  const [orders, setOrders] = useState<ThirdPartyOrder[]>([]);
  const [addresses, setAddresses] = useState<CustomerAddress[]>([]);
  const [loading, setLoading] = useState(true);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [orderFilterStatus, setOrderFilterStatus] = useState('ALL');

  // 购物车状态
  const [cart, setCart] = useState<CartItem[]>([]);
  const [isCartOpen, setIsCartOpen] = useState(false);
  const [isCheckingOut, setIsCheckingOut] = useState(false);

  // 地址状态
  const [selectedAddress, setSelectedAddress] = useState<CustomerAddress | null>(null);
  const [isAddressModalOpen, setIsAddressModalOpen] = useState(false);

  // 订单弹窗与物流弹窗
  const [isOrdersListModalOpen, setIsOrdersListModalOpen] = useState(false);
  const [selectedDetailOrder, setSelectedDetailOrder] = useState<ThirdPartyOrder | null>(null);
  const [isOrderDetailModalOpen, setIsOrderDetailModalOpen] = useState(false);
  const [selectedLogisticsOrder, setSelectedLogisticsOrder] = useState<ThirdPartyOrder | null>(null);
  const [isLogisticsModalOpen, setIsLogisticsModalOpen] = useState(false);

  // 选规格购买/加购弹窗
  const [buyingProduct, setBuyingProduct] = useState<ThirdPartyProduct | null>(null);
  const [selectedSku, setSelectedSku] = useState<ThirdPartySku | null>(null);
  const [selectedAttrs, setSelectedAttrs] = useState<Record<string, string>>({});
  const [buyQuantity, setBuyQuantity] = useState(1);
  const [showSpecsModal, setShowSpecsModal] = useState<ThirdPartyProduct | null>(null);

  // 智能客服 Chat
  const [showChatModal, setShowChatModal] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<Array<{ role: 'user' | 'assistant'; text: string; time: string }>>([
    {
      role: 'assistant',
      text: '您好！我是极光潮品官方智能客服。请问有什么可以帮您？支持多订单查询、极速修改收货地址、售后退换货与物流进度追踪。',
      time: new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
    },
  ]);
  const [isChatSending, setIsChatSending] = useState(false);

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

  // 获取地址簿
  const fetchAddresses = async () => {
    try {
      const res = await fetch('/api/store/addresses?customerId=CUST-8801');
      const data = await res.json();
      if (data.success && data.addresses) {
        setAddresses(data.addresses);
        if (!selectedAddress && data.addresses.length > 0) {
          const defaultAddr = data.addresses.find((a: CustomerAddress) => a.isDefault) || data.addresses[0];
          setSelectedAddress(defaultAddr);
        }
      }
    } catch (err) {
      console.error('Failed to load addresses:', err);
    }
  };

  // 获取订单列表
  const fetchOrders = async (status = 'ALL') => {
    try {
      setOrdersLoading(true);
      const query = status && status !== 'ALL' ? `&status=${status}` : '';
      const res = await fetch(`/api/store/orders?userId=CUST-8801${query}`);
      const data = await res.json();
      if (data.success) {
        setOrders(data.orders || []);
      }
    } catch (err) {
      console.error('Failed to load orders:', err);
    } finally {
      setOrdersLoading(false);
    }
  };

  useEffect(() => {
    fetchProducts();
    fetchAddresses();
    fetchOrders('ALL');
  }, []);

  // 打开选规格弹窗
  const handleOpenBuyModal = (product: ThirdPartyProduct) => {
    setBuyingProduct(product);
    setBuyQuantity(1);
    if (product.skus && product.skus.length > 0) {
      const firstSku = product.skus[0];
      setSelectedSku(firstSku);
      setSelectedAttrs(firstSku.specAttributes || {});
    } else {
      setSelectedSku(null);
      setSelectedAttrs({});
    }
  };

  // 切换规格属性
  const handleSelectAttr = (dimName: string, val: string) => {
    if (!buyingProduct || !buyingProduct.skus) return;
    const nextAttrs = { ...selectedAttrs, [dimName]: val };
    setSelectedAttrs(nextAttrs);

    const matched = buyingProduct.skus.find((sku) => {
      return Object.entries(nextAttrs).every(([k, v]) => sku.specAttributes[k] === v);
    });

    if (matched) {
      setSelectedSku(matched);
    } else {
      const partial = buyingProduct.skus.find((sku) => sku.specAttributes[dimName] === val);
      if (partial) {
        setSelectedSku(partial);
        setSelectedAttrs(partial.specAttributes);
      }
    }
  };

  // 加入购物车
  const handleAddToCart = () => {
    if (!buyingProduct || !selectedSku) return;

    setCart((prevCart) => {
      const existingIdx = prevCart.findIndex((item) => item.skuCode === selectedSku.skuCode);
      if (existingIdx >= 0) {
        const next = [...prevCart];
        const item = next[existingIdx];
        const newQty = Math.min(item.quantity + buyQuantity, item.stock);
        next[existingIdx] = { ...item, quantity: newQty };
        return next;
      }

      const newItem: CartItem = {
        id: selectedSku.skuCode,
        spuId: buyingProduct.productId,
        skuCode: selectedSku.skuCode,
        title: buyingProduct.title,
        skuTitle: selectedSku.skuTitle,
        imageUrl: selectedSku.imageUrl || buyingProduct.imageUrl || '',
        price: Number(selectedSku.price),
        quantity: buyQuantity,
        stock: selectedSku.stock,
        specAttributes: selectedSku.specAttributes || selectedAttrs,
        selected: true,
      };
      return [...prevCart, newItem];
    });

    setBuyingProduct(null);
    setIsCartOpen(true);
  };

  // 购物车数量更新
  const handleUpdateCartQuantity = (skuCode: string, delta: number) => {
    setCart((prev) =>
      prev.map((item) => {
        if (item.skuCode === skuCode) {
          const nextQty = Math.max(1, Math.min(item.stock, item.quantity + delta));
          return { ...item, quantity: nextQty };
        }
        return item;
      }),
    );
  };

  const handleToggleSelectCartItem = (skuCode: string) => {
    setCart((prev) => prev.map((item) => (item.skuCode === skuCode ? { ...item, selected: !item.selected } : item)));
  };

  const handleToggleSelectAllCart = () => {
    const allSelected = cart.every((i) => i.selected);
    setCart((prev) => prev.map((item) => ({ ...item, selected: !allSelected })));
  };

  const handleRemoveCartItem = (skuCode: string) => {
    setCart((prev) => prev.filter((item) => item.skuCode !== skuCode));
  };

  const handleClearCart = () => {
    setCart([]);
  };

  // 新增收货地址
  const handleAddNewAddress = async (newAddr: {
    recipientName: string;
    phone: string;
    province: string;
    city: string;
    district: string;
    detailAddress: string;
    isDefault: boolean;
  }) => {
    const res = await fetch('/api/store/addresses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        customerId: 'CUST-8801',
        ...newAddr,
      }),
    });
    const data = await res.json();
    if (data.success && data.address) {
      await fetchAddresses();
      setSelectedAddress(data.address);
    } else {
      throw new Error(data.message || '新增收货地址失败');
    }
  };

  // 购物车批量结算
  const handleCartCheckout = async () => {
    const selectedItems = cart.filter((i) => i.selected);
    if (selectedItems.length === 0 || !selectedAddress) return;

    try {
      setIsCheckingOut(true);
      const res = await fetch('/api/store/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customerId: 'CUST-8801',
          items: selectedItems.map((item) => ({
            skuCode: item.skuCode,
            quantity: item.quantity,
          })),
          shippingAddress: selectedAddress.fullAddress,
          recipientName: selectedAddress.recipientName,
          recipientPhone: selectedAddress.phone,
        }),
      });

      const data = await res.json();
      if (data.success) {
        // 移除已结算条目
        const selectedCodes = new Set(selectedItems.map((i) => i.skuCode));
        setCart((prev) => prev.filter((i) => !selectedCodes.has(i.skuCode)));
        setIsCartOpen(false);

        // 刷新列表并打开订单详情
        await fetchProducts();
        await fetchOrders(orderFilterStatus);

        alert(`🎉 下单成功！订单号: ${data.orderId}`);
      } else {
        alert(`结算失败: ${data.message || '请稍后重试'}`);
      }
    } catch (err) {
      alert('网络异常，结算失败');
    } finally {
      setIsCheckingOut(false);
    }
  };

  // 单件商品立即购买
  const handleInstantBuy = async () => {
    if (!buyingProduct || !selectedSku || !selectedAddress) return;
    try {
      setIsCheckingOut(true);
      const res = await fetch('/api/store/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customerId: 'CUST-8801',
          items: [{ skuCode: selectedSku.skuCode, quantity: buyQuantity }],
          shippingAddress: selectedAddress.fullAddress,
          recipientName: selectedAddress.recipientName,
          recipientPhone: selectedAddress.phone,
        }),
      });

      const data = await res.json();
      if (data.success) {
        setBuyingProduct(null);
        await fetchProducts();
        await fetchOrders(orderFilterStatus);
        alert(`🎉 下单成功！订单号: ${data.orderId}`);
      } else {
        alert(`下单失败: ${data.message || '请稍后重试'}`);
      }
    } catch (err) {
      alert('网络异常，下单失败');
    } finally {
      setIsCheckingOut(false);
    }
  };

  // 咨询客服联动
  const handleOpenChatWithOrder = (orderId: string, initialPrompt?: string) => {
    const prompt = initialPrompt || `我想咨询关于订单 ${orderId} 的相关信息`;
    setShowChatModal(true);
    setChatInput(prompt);
  };

  // 发送客服对话
  const handleSendChatMessage = async () => {
    if (!chatInput.trim() || isChatSending) return;
    const userMsg = chatInput.trim();
    setChatInput('');
    const nowTime = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });

    setChatMessages((prev) => [...prev, { role: 'user', text: userMsg, time: nowTime }]);
    setIsChatSending(true);

    try {
      const gatewayUrl = process.env.NEXT_PUBLIC_GATEWAY_URL || 'http://localhost:4000';
      const targetUrl = `${gatewayUrl}/api/chat`;
      const resp = await fetch(targetUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMsg,
          input: userMsg,
          businessId: 'aurora',
          userId: 'CUST-8801',
          userEmail: 'zhangwei@example.com',
          sync: true,
        }),
      });

      const data = await resp.json();
      const replyText = data.output || data.result || '已为您处理完毕。';

      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: replyText,
          time: new Date().toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          }),
        },
      ]);
      // 如果触发了改地址或退款，实时刷新订单
      fetchOrders(orderFilterStatus);
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: '系统已接收到您的请求，正在通过极光潮品 SPI 远程处理中...',
          time: new Date().toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          }),
        },
      ]);
    } finally {
      setIsChatSending(false);
    }
  };

  const totalCartCount = cart.reduce((s, i) => s + i.quantity, 0);

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans">
      {/* 顶部电商导航栏 */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-xs">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-lg bg-emerald-600 flex items-center justify-center text-white font-bold text-xl shadow-xs">
              A
            </div>
            <div>
              <div className="font-bold text-lg text-slate-900 tracking-tight flex items-center space-x-2">
                <span>极光潮品 AURORA LUXE</span>
                <span className="text-xs bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded font-medium">
                  独立自研商城
                </span>
              </div>
              <div className="text-xs text-slate-500">独立数据库物理隔离 · SPU / SKU 多规格电商体系 (Port 3005)</div>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            {/* 顾客标识 */}
            <div className="hidden md:flex items-center text-xs text-slate-600 bg-slate-100 px-3 py-1.5 rounded-full">
              <span className="w-2 h-2 rounded-full bg-emerald-500 mr-2"></span>
              当前顾客: <strong className="ml-1 text-slate-800">张伟 (黑金SVIP)</strong>
            </div>

            {/* 收货地址快捷入口 */}
            <button
              type="button"
              onClick={() => setIsAddressModalOpen(true)}
              className="px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition shadow-2xs flex items-center space-x-1.5 cursor-pointer"
            >
              <span>📍 地址簿</span>
              <span className="text-slate-400">({addresses.length})</span>
            </button>

            {/* 我的订单入口 */}
            <button
              type="button"
              onClick={() => {
                setIsOrdersListModalOpen(true);
                fetchOrders(orderFilterStatus);
              }}
              className="px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition shadow-2xs flex items-center space-x-1.5 cursor-pointer"
            >
              <span>📋 我的订单</span>
              {orders.length > 0 && (
                <span className="bg-emerald-600 text-white text-[11px] px-1.5 py-0.2 rounded-full font-bold">
                  {orders.length}
                </span>
              )}
            </button>

            {/* 购物车入口 */}
            <button
              type="button"
              onClick={() => setIsCartOpen(true)}
              className="px-3 py-1.5 text-xs font-semibold text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 transition shadow-2xs flex items-center space-x-1.5 cursor-pointer"
            >
              <span>🛒 购物车</span>
              {totalCartCount > 0 && (
                <span className="bg-emerald-600 text-white text-[11px] px-1.5 py-0.2 rounded-full font-bold">
                  {totalCartCount}
                </span>
              )}
            </button>

            {/* 管理后台跳转 */}
            <a
              href="/admin"
              className="px-3 py-1.5 text-xs font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 transition hidden sm:inline-flex items-center space-x-1"
            >
              <span>⚙️ 商户后台</span>
            </a>
          </div>
        </div>
      </header>

      {/* 商城 Banner */}
      <section className="bg-gradient-to-r from-slate-900 via-slate-800 to-emerald-950 text-white py-10 px-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
          <div>
            <span className="text-xs bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2.5 py-1 rounded-full uppercase tracking-wider font-semibold">
              2026 SPU + SKU 多规格旗舰首发
            </span>
            <h1 className="text-3xl sm:text-4xl font-extrabold mt-3 tracking-tight">极简机能 · 严选面料与多维规格</h1>
            <p className="text-slate-300 text-sm mt-2 max-w-xl">
              全系采用独立商品 SPU 建模，提供详尽材质技术参数、多颜色尺码 SKU 矩阵与智能库存同步。支持通过 AI
              智能客服极速改单。
            </p>
          </div>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => setShowChatModal(true)}
              className="px-5 py-2.5 bg-emerald-600 text-white font-medium rounded-lg hover:bg-emerald-500 transition shadow-sm flex items-center space-x-2 text-sm cursor-pointer"
            >
              <span>💬 咨询在线智能客服</span>
            </button>
          </div>
        </div>
      </section>

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
              <div key={n} className="bg-white rounded-xl border border-slate-200 p-4 h-80 animate-pulse"></div>
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
                  <div className="w-full h-44 bg-slate-100 rounded-lg overflow-hidden mb-3 relative flex items-center justify-center">
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
                  </div>

                  <span className="text-[11px] uppercase tracking-wider text-emerald-600 font-semibold mb-1">
                    {product.category || '潮流单品'}
                  </span>
                  <h3 className="font-bold text-slate-900 text-sm line-clamp-2 leading-snug">{product.title}</h3>
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
                  <button
                    type="button"
                    onClick={() => setShowSpecsModal(product)}
                    className="flex-1 py-1.5 bg-white border border-slate-300 text-slate-700 text-xs font-semibold rounded-lg hover:bg-slate-100 transition cursor-pointer"
                  >
                    参数规格
                  </button>
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
              {/* 商品概览 */}
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

              {/* 规格维度选择器 (Color, Size, etc.) */}
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

              {/* 数量选择 */}
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

              {/* 当前默认配送地址预览 */}
              <div className="bg-emerald-50/60 p-3 rounded-xl border border-emerald-200 flex items-center justify-between text-xs">
                <div className="flex items-center space-x-2">
                  <span className="text-emerald-700">📍</span>
                  <div className="text-slate-700">
                    配送至：
                    <strong className="text-slate-900 ml-1">
                      {selectedAddress ? selectedAddress.recipientName : '张伟'}
                    </strong>{' '}
                    ({selectedAddress?.fullAddress || '北京市海淀区中关村南大街1号院8号楼1201室'})
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setIsAddressModalOpen(true)}
                  className="text-emerald-700 font-semibold hover:underline shrink-0 ml-2"
                >
                  修改
                </button>
              </div>
            </div>

            {/* 弹窗底部双操作按钮 (加入购物车 / 立即购买) */}
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
              <Button
                type="button"
                size="sm"
                onClick={handleInstantBuy}
                disabled={isCheckingOut || !selectedSku || selectedSku.stock <= 0}
                className="bg-emerald-600 text-white text-xs font-bold hover:bg-emerald-500 shadow-xs"
              >
                {isCheckingOut ? '正在提交...' : '⚡ 立即购买'}
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>

      {/* 参数规格查看抽屉 (Specs Modal) */}
      <Dialog open={Boolean(showSpecsModal)} onOpenChange={(open) => !open && setShowSpecsModal(null)}>
        {showSpecsModal && (
          <DialogContent className="max-w-md p-6">
            <DialogHeader className="pb-3 border-b border-slate-100">
              <DialogTitle className="text-base font-bold text-slate-900">{showSpecsModal.title}</DialogTitle>
              <p className="text-[11px] text-emerald-600 font-medium">{showSpecsModal.brand} · 材质与技术参数</p>
            </DialogHeader>

            <div className="py-3 space-y-3">
              <div className="text-xs text-slate-600 bg-slate-50 p-3 rounded-lg leading-relaxed">
                {showSpecsModal.description}
              </div>

              <div className="border border-slate-200 rounded-lg overflow-hidden">
                <table className="w-full text-left text-xs">
                  <tbody className="divide-y divide-slate-100">
                    {Object.entries(showSpecsModal.specs || {}).map(([key, value]) => (
                      <tr key={key} className="bg-white">
                        <td className="p-2.5 bg-slate-50 text-slate-500 font-semibold w-28">{key}</td>
                        <td className="p-2.5 text-slate-800">{value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <DialogFooter>
              <Button
                type="button"
                size="sm"
                onClick={() => setShowSpecsModal(null)}
                className="bg-slate-900 text-white text-xs font-semibold"
              >
                关闭
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>

      {/* 购物车抽屉 */}
      <CartDrawer
        isOpen={isCartOpen}
        onClose={() => setIsCartOpen(false)}
        cart={cart}
        onUpdateQuantity={handleUpdateCartQuantity}
        onToggleSelect={handleToggleSelectCartItem}
        onToggleSelectAll={handleToggleSelectAllCart}
        onRemoveItem={handleRemoveCartItem}
        onClearCart={handleClearCart}
        selectedAddress={selectedAddress}
        onOpenAddressModal={() => setIsAddressModalOpen(true)}
        onCheckout={handleCartCheckout}
        isCheckingOut={isCheckingOut}
      />

      {/* 地址簿管理弹窗 */}
      <AddressModal
        isOpen={isAddressModalOpen}
        onClose={() => setIsAddressModalOpen(false)}
        addresses={addresses}
        selectedAddressId={selectedAddress?.id}
        onSelectAddress={(addr) => setSelectedAddress(addr)}
        onAddAddress={handleAddNewAddress}
      />

      {/* 订单列表中心弹窗 */}
      <OrdersListModal
        isOpen={isOrdersListModalOpen}
        onClose={() => setIsOrdersListModalOpen(false)}
        orders={orders}
        loading={ordersLoading}
        currentStatus={orderFilterStatus}
        onFilterStatus={(status) => {
          setOrderFilterStatus(status);
          fetchOrders(status);
        }}
        onSelectOrder={(order) => {
          setSelectedDetailOrder(order);
          setIsOrderDetailModalOpen(true);
        }}
        onOpenLogistics={(order) => {
          setSelectedLogisticsOrder(order);
          setIsLogisticsModalOpen(true);
        }}
        onOpenChatWithOrder={handleOpenChatWithOrder}
      />

      {/* 订单详情快照弹窗 */}
      <OrderDetailModal
        isOpen={isOrderDetailModalOpen}
        onClose={() => setIsOrderDetailModalOpen(false)}
        order={selectedDetailOrder}
        onOpenLogistics={(order) => {
          setSelectedLogisticsOrder(order);
          setIsLogisticsModalOpen(true);
        }}
        onOpenChatWithOrder={handleOpenChatWithOrder}
      />

      {/* 物流实时轨迹弹窗 */}
      <LogisticsModal
        isOpen={isLogisticsModalOpen}
        onClose={() => setIsLogisticsModalOpen(false)}
        order={selectedLogisticsOrder}
        onOpenChatWithOrder={handleOpenChatWithOrder}
      />

      {/* 右下角悬浮客服与购物车气泡 */}
      <div className="fixed bottom-6 right-6 z-40 flex flex-col items-end space-y-3">
        {totalCartCount > 0 && (
          <button
            type="button"
            onClick={() => setIsCartOpen(true)}
            className="px-4 py-3 bg-amber-500 text-white font-bold rounded-full shadow-lg hover:bg-amber-400 hover:shadow-xl transition-all flex items-center space-x-2 text-xs border-2 border-white cursor-pointer"
          >
            <span className="text-base">🛒</span>
            <span>购物车 ({totalCartCount})</span>
          </button>
        )}

        <button
          type="button"
          onClick={() => setShowChatModal(!showChatModal)}
          className="px-4 py-3 bg-emerald-600 text-white font-semibold rounded-full shadow-lg hover:bg-emerald-500 hover:shadow-xl transition-all flex items-center space-x-2 text-xs border-2 border-white cursor-pointer"
        >
          <span className="text-base">💬</span>
          <span>极光智能客服</span>
        </button>
      </div>

      {/* 客服对话弹窗 */}
      {showChatModal && (
        <div className="fixed bottom-20 right-6 z-50 w-96 max-w-[calc(100vw-2rem)] h-[520px] bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col overflow-hidden animate-in fade-in slide-in-from-bottom-4">
          <div className="bg-emerald-700 text-white px-4 py-3 flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-300 animate-pulse"></span>
              <div>
                <div className="font-bold text-sm">极光潮品 AI 智能客服</div>
                <div className="text-xs text-emerald-200">已连接外部商户 SPI 协议</div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setShowChatModal(false)}
              className="text-white/80 hover:text-white text-lg font-bold cursor-pointer"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 p-4 overflow-y-auto space-y-3 bg-slate-50 text-sm">
            {chatMessages.map((msg, idx) => (
              <div key={idx} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 ${
                    msg.role === 'user'
                      ? 'bg-emerald-600 text-white rounded-tr-xs'
                      : 'bg-white text-slate-800 border border-slate-200 shadow-2xs rounded-tl-xs whitespace-pre-wrap'
                  }`}
                >
                  {msg.text}
                </div>
                <span className="text-[10px] text-slate-400 mt-1 px-1">{msg.time}</span>
              </div>
            ))}
            {isChatSending && (
              <div className="flex items-center space-x-2 text-xs text-slate-500 italic p-2 bg-white rounded-lg border border-slate-200 w-fit">
                <span className="animate-spin text-emerald-600">⚡</span>
                <span>AI 决策引擎正在通过 SPI 调度商户系统...</span>
              </div>
            )}
          </div>

          <div className="p-2 bg-white border-t border-slate-100 flex gap-1.5 overflow-x-auto text-xs">
            <button
              type="button"
              onClick={() => setChatInput('帮我把刚才的订单地址改成朝阳区望京SOHO T1 1508室')}
              className="px-2 py-1 bg-slate-100 text-slate-700 hover:bg-emerald-50 hover:text-emerald-700 rounded whitespace-nowrap transition cursor-pointer"
            >
              🚀 帮我改地址为望京SOHO
            </button>
            <button
              type="button"
              onClick={() => setChatInput('我想把订单 AURORA-ORD-2026-9081 申请退款')}
              className="px-2 py-1 bg-slate-100 text-slate-700 hover:bg-emerald-50 hover:text-emerald-700 rounded whitespace-nowrap transition cursor-pointer"
            >
              💸 申请退款
            </button>
          </div>

          <div className="p-3 bg-white border-t border-slate-200 flex items-center space-x-2">
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendChatMessage()}
              placeholder="输入您的问题（如改地址、查单、退款）..."
              className="flex-1 text-sm px-3 py-2 border border-slate-300 rounded-lg focus:outline-emerald-500"
            />
            <button
              type="button"
              onClick={handleSendChatMessage}
              disabled={!chatInput.trim() || isChatSending}
              className="px-3.5 py-2 bg-emerald-600 text-white rounded-lg text-sm font-semibold hover:bg-emerald-500 disabled:opacity-40 transition cursor-pointer"
            >
              发送
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
