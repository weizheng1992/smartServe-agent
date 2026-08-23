'use client';

import React, { useEffect, useState } from 'react';
import type { ThirdPartyOrder, ThirdPartyProduct, ThirdPartySku } from 'types';

export default function StorefrontPage() {
  const [products, setProducts] = useState<ThirdPartyProduct[]>([]);
  const [orders, setOrders] = useState<ThirdPartyOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [ordersLoading, setOrdersLoading] = useState(false);

  // 下单与多规格选购状态
  const [buyingProduct, setBuyingProduct] = useState<ThirdPartyProduct | null>(null);
  const [selectedSku, setSelectedSku] = useState<ThirdPartySku | null>(null);
  const [selectedAttrs, setSelectedAttrs] = useState<Record<string, string>>({});
  const [selectedAddress, setSelectedAddress] = useState('北京市海淀区中关村南大街1号院8号楼1201室');
  const [recipientName, setRecipientName] = useState('张伟');
  const [recipientPhone, setRecipientPhone] = useState('13800138000');
  const [submittingOrder, setSubmittingOrder] = useState(false);

  // 弹窗与抽屉
  const [showOrdersModal, setShowOrdersModal] = useState(false);
  const [showSpecsModal, setShowSpecsModal] = useState<ThirdPartyProduct | null>(null);
  const [showChatModal, setShowChatModal] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<Array<{ role: 'user' | 'assistant'; text: string; time: string }>>([
    {
      role: 'assistant',
      text: '您好！我是极光潮品官方智能客服。请问有什么可以帮您？支持查询订单、极速修改收货地址、办理退换货或咨询现货规格库存。',
      time: new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
    },
  ]);
  const [isChatSending, setIsChatSending] = useState(false);

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

  const fetchOrders = async () => {
    try {
      setOrdersLoading(true);
      const orderRes = await fetch('/api/store/orders?userId=CUST-8801');
      const orderJson = await orderRes.json();
      if (orderJson.success) setOrders(orderJson.orders || []);
    } catch (err) {
      console.error('Failed to load orders:', err);
    } finally {
      setOrdersLoading(false);
    }
  };

  const handleOpenOrdersModal = () => {
    setShowOrdersModal(true);
    fetchOrders();
  };

  useEffect(() => {
    fetchProducts();
  }, []);

  // 打开购买弹窗时自动选中首个可用 SKU
  const handleOpenBuyModal = (product: ThirdPartyProduct) => {
    setBuyingProduct(product);
    if (product.skus && product.skus.length > 0) {
      const firstSku = product.skus[0];
      setSelectedSku(firstSku);
      setSelectedAttrs(firstSku.specAttributes || {});
    } else {
      setSelectedSku(null);
      setSelectedAttrs({});
    }
  };

  // 选择规格维度属性 (如切换颜色或尺码)
  const handleSelectAttr = (dimName: string, val: string) => {
    if (!buyingProduct || !buyingProduct.skus) return;
    const nextAttrs = { ...selectedAttrs, [dimName]: val };
    setSelectedAttrs(nextAttrs);

    // 匹配对应的 SKU
    const matched = buyingProduct.skus.find((sku) => {
      return Object.entries(nextAttrs).every(([k, v]) => sku.specAttributes[k] === v);
    });

    if (matched) {
      setSelectedSku(matched);
    } else {
      // 找不到完全匹配的则尝试寻找部分匹配
      const partial = buyingProduct.skus.find((sku) => sku.specAttributes[dimName] === val);
      if (partial) {
        setSelectedSku(partial);
        setSelectedAttrs(partial.specAttributes);
      }
    }
  };

  const handlePlaceOrder = async () => {
    if (!buyingProduct) return;
    const targetSkuCode = selectedSku?.skuCode || buyingProduct.skus?.[0]?.skuCode || buyingProduct.productId;

    setSubmittingOrder(true);
    try {
      const resp = await fetch('/api/store/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customerId: 'CUST-8801',
          skuCode: targetSkuCode,
          quantity: 1,
          shippingAddress: selectedAddress,
          recipientName,
          recipientPhone,
        }),
      });
      const data = await resp.json();
      if (data.success) {
        alert(`🎉 下单成功！订单编号: ${data.orderId}`);
        setBuyingProduct(null);
        fetchProducts();
        if (showOrdersModal) {
          fetchOrders();
        }
      } else {
        alert(`下单失败: ${data.message || '系统繁忙'}`);
      }
    } catch (err) {
      alert('网络异常，下单失败');
    } finally {
      setSubmittingOrder(false);
    }
  };

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
      const resp = await fetch('http://localhost:3000/api/chat', {
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

          <div className="flex items-center space-x-4">
            <div className="hidden sm:flex items-center text-xs text-slate-600 bg-slate-100 px-3 py-1.5 rounded-full">
              <span className="w-2 h-2 rounded-full bg-emerald-500 mr-2"></span>
              当前顾客: <strong className="ml-1 text-slate-800">张伟 (黑金SVIP)</strong>
            </div>

            <button
              type="button"
              onClick={handleOpenOrdersModal}
              className="px-3 py-1.5 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition shadow-xs flex items-center space-x-1 cursor-pointer"
            >
              <span>📋 我的订单</span>
              {orders.length > 0 && (
                <span className="bg-emerald-600 text-white text-xs px-1.5 py-0.2 rounded-full ml-1 font-bold">
                  {orders.length}
                </span>
              )}
            </button>

            <a
              href="/admin"
              className="px-3 py-1.5 text-sm font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 transition flex items-center space-x-1"
            >
              <span>⚙️ 商户后台管理</span>
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

      {/* SPU / SKU 选规格下单弹窗 */}
      {buyingProduct && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-xl border border-slate-200 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-base font-bold text-slate-900">选择商品规格与收货地址</h3>
              <button
                type="button"
                onClick={() => setBuyingProduct(null)}
                className="text-slate-400 hover:text-slate-600 text-xl font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="py-4 space-y-4">
              {/* 商品概览 */}
              <div className="bg-slate-50 p-3 rounded-xl flex items-center space-x-3 border border-slate-200">
                <img
                  src={
                    selectedSku?.imageUrl ||
                    buyingProduct.imageUrl ||
                    'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=200'
                  }
                  alt="SKU"
                  className="w-16 h-16 rounded-lg object-cover border border-slate-200 bg-white"
                />
                <div className="flex-1">
                  <div className="font-semibold text-slate-900 text-xs line-clamp-1">
                    {selectedSku?.skuTitle || buyingProduct.title}
                  </div>
                  <div className="text-emerald-600 font-extrabold text-lg mt-0.5">
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

              {/* 收件人与地址 */}
              <div className="pt-2 border-t border-slate-100 space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">收货人姓名 & 联系电话</label>
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      type="text"
                      value={recipientName}
                      onChange={(e) => setRecipientName(e.target.value)}
                      className="px-3 py-2 text-xs border border-slate-300 rounded-lg focus:outline-emerald-500"
                    />
                    <input
                      type="text"
                      value={recipientPhone}
                      onChange={(e) => setRecipientPhone(e.target.value)}
                      className="px-3 py-2 text-xs border border-slate-300 rounded-lg focus:outline-emerald-500"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">配送地址簿</label>
                  <select
                    value={selectedAddress}
                    onChange={(e) => setSelectedAddress(e.target.value)}
                    className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg focus:outline-emerald-500 bg-white"
                  >
                    <option value="北京市海淀区中关村南大街1号院8号楼1201室">
                      北京市海淀区中关村南大街1号院8号楼1201室 (默认)
                    </option>
                    <option value="北京市朝阳区建国门外大街1号国贸大厦A座 3801室">
                      北京市朝阳区建国门外大街1号国贸大厦A座 3801室 (国贸)
                    </option>
                    <option value="北京市朝阳区望京SOHO T1座 1508室">北京市朝阳区望京SOHO T1座 1508室 (公司)</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="pt-4 border-t border-slate-100 flex items-center justify-end space-x-3">
              <button
                type="button"
                onClick={() => setBuyingProduct(null)}
                className="px-4 py-2 text-xs text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handlePlaceOrder}
                disabled={submittingOrder || !selectedSku || selectedSku.stock <= 0}
                className="px-5 py-2 text-xs font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 transition shadow-xs disabled:opacity-50 cursor-pointer"
              >
                {submittingOrder
                  ? '正在提交订单...'
                  : selectedSku && selectedSku.stock <= 0
                    ? '该规格已售罄'
                    : '确认支付并下单'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 参数规格查看抽屉 (Specs Modal) */}
      {showSpecsModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-slate-200">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900">{showSpecsModal.title}</h3>
                <span className="text-[11px] text-emerald-600 font-medium">
                  {showSpecsModal.brand} · 材质与技术参数
                </span>
              </div>
              <button
                type="button"
                onClick={() => setShowSpecsModal(null)}
                className="text-slate-400 hover:text-slate-600 text-xl font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="py-4 space-y-3">
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

            <div className="pt-3 border-t border-slate-100 flex justify-end">
              <button
                type="button"
                onClick={() => setShowSpecsModal(null)}
                className="px-4 py-1.5 text-xs font-semibold bg-slate-900 text-white rounded-lg cursor-pointer"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 我的订单抽屉 (Orders Modal) */}
      {showOrdersModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-2xl w-full p-6 shadow-xl border border-slate-200 max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between pb-4 border-b border-slate-100">
              <div>
                <h3 className="text-lg font-bold text-slate-900">我的订单列表</h3>
                <p className="text-xs text-slate-500 mt-0.5">顾客 ID: 张伟 (CUST-8801)</p>
              </div>
              <button
                type="button"
                onClick={() => setShowOrdersModal(false)}
                className="text-slate-400 hover:text-slate-600 text-xl font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="py-4 overflow-y-auto flex-1 space-y-4">
              {ordersLoading ? (
                <div className="space-y-3 py-6">
                  <div className="h-24 bg-slate-100 rounded-xl animate-pulse" />
                  <div className="h-24 bg-slate-100 rounded-xl animate-pulse" />
                </div>
              ) : orders.length === 0 ? (
                <div className="text-center py-12 text-slate-400 text-sm">暂无订单记录，去商城挑选一件吧！</div>
              ) : (
                orders.map((order) => (
                  <div key={order.orderId} className="border border-slate-200 rounded-xl p-4 bg-slate-50/50 space-y-3">
                    <div className="flex items-center justify-between text-xs text-slate-500 border-b border-slate-100 pb-2">
                      <div className="flex items-center space-x-2">
                        <span>
                          订单号: <strong className="text-slate-800">{order.orderId}</strong>
                        </span>
                        <span>·</span>
                        <span>{new Date(order.createdAt).toLocaleDateString()}</span>
                      </div>
                      <span
                        className={`px-2.5 py-0.5 rounded-full font-semibold ${
                          order.status === 'PAID'
                            ? 'bg-amber-100 text-amber-800'
                            : order.status === 'SHIPPED'
                              ? 'bg-blue-100 text-blue-800'
                              : order.status === 'REFUNDED'
                                ? 'bg-purple-100 text-purple-800'
                                : 'bg-slate-100 text-slate-800'
                        }`}
                      >
                        {order.status === 'PAID' && '待发货'}
                        {order.status === 'SHIPPED' && '已发货'}
                        {order.status === 'REFUNDED' && '已退款'}
                        {!['PAID', 'SHIPPED', 'REFUNDED'].includes(order.status) && order.status}
                      </span>
                    </div>

                    <div className="space-y-2">
                      {order.items.map((item, idx) => (
                        <div key={idx} className="flex justify-between items-center text-xs">
                          <div>
                            <span className="text-slate-900 font-medium">{item.title}</span>
                            {item.specSummary && (
                              <span className="text-[11px] text-slate-500 bg-slate-200 px-1.5 py-0.2 rounded ml-2">
                                {item.specSummary}
                              </span>
                            )}
                          </div>
                          <span className="text-slate-600 font-semibold">
                            x{item.quantity} · ¥{Number(item.price).toFixed(2)}
                          </span>
                        </div>
                      ))}
                    </div>

                    <div className="pt-2 border-t border-slate-100 text-xs text-slate-600 space-y-1">
                      <div>
                        📍 配送地址: <strong className="text-slate-800">{order.shippingAddress.fullAddress}</strong>
                      </div>
                      <div>
                        👤 收件人: {order.shippingAddress.recipientName} ({order.shippingAddress.phone})
                      </div>
                      {order.tracking && (
                        <div className="text-blue-600 font-medium">
                          🚚 物流单号: {order.tracking.carrier} - {order.tracking.trackingNumber}
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* 右下角悬浮在线客服入口 */}
      <div className="fixed bottom-6 right-6 z-40">
        <button
          type="button"
          onClick={() => setShowChatModal(!showChatModal)}
          className="px-4 py-3 bg-emerald-600 text-white font-semibold rounded-full shadow-lg hover:bg-emerald-500 hover:shadow-xl transition-all flex items-center space-x-2 text-sm border-2 border-white cursor-pointer"
        >
          <span className="text-lg">💬</span>
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
