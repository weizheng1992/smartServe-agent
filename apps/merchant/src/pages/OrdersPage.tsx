import React, { useEffect, useState } from 'react';
import { Link } from 'react-router';
import type { ThirdPartyOrder } from 'types';
import { StorefrontHeader } from '../components/navbar/StorefrontHeader';
import { LogisticsModal } from '../components/orders/LogisticsModal';
import { OrderDetailModal } from '../components/orders/OrderDetailModal';
import { useCurrentUser } from '../context/UserContext';

function parseAddress(addr: any) {
  if (!addr) {
    return {
      recipientName: '张伟',
      phone: '13800138000',
      fullAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
    };
  }
  if (typeof addr === 'string') {
    try {
      const parsed = JSON.parse(addr);
      if (typeof parsed === 'object' && parsed !== null) {
        return {
          recipientName: parsed.recipientName || '张伟',
          phone: parsed.phone || '13800138000',
          fullAddress: parsed.fullAddress || addr,
        };
      }
    } catch {
      // plain text string
    }
    return {
      recipientName: '张伟',
      phone: '13800138000',
      fullAddress: addr,
    };
  }
  return {
    recipientName: addr.recipientName || '张伟',
    phone: addr.phone || '13800138000',
    fullAddress: addr.fullAddress || '北京市海淀区中关村南大街1号院8号楼1201室',
  };
}

export default function OrdersPage() {
  const { user } = useCurrentUser();
  const [orders, setOrders] = useState<ThirdPartyOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('ALL');

  const [selectedDetailOrder, setSelectedDetailOrder] = useState<ThirdPartyOrder | null>(null);
  const [isOrderDetailModalOpen, setIsOrderDetailModalOpen] = useState(false);
  const [selectedLogisticsOrder, setSelectedLogisticsOrder] = useState<ThirdPartyOrder | null>(null);
  const [isLogisticsModalOpen, setIsLogisticsModalOpen] = useState(false);

  const fetchOrders = async (status = 'ALL', targetUserId = user.id) => {
    setLoading(true);
    try {
      const url =
        status === 'ALL'
          ? `/api/store/orders?customerId=${targetUserId}`
          : `/api/store/orders?customerId=${targetUserId}&status=${status}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.success && data.orders) {
        setOrders(data.orders);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders(filterStatus, user.id);
  }, [filterStatus, user.id]);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'PAID':
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
            已支付 · 待发货
          </span>
        );
      case 'SHIPPED':
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
            运输中 · 顺丰速运
          </span>
        );
      case 'DELIVERED':
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-700 border border-slate-200">
            已签收
          </span>
        );
      case 'REFUNDED':
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
            已全额退款
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-50 text-slate-600 border border-slate-200">
            {status}
          </span>
        );
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <StorefrontHeader ordersCount={orders.length} />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-slate-900 flex items-center space-x-2">
              <span>📋 我的订单中心</span>
              <span className="text-xs font-normal text-slate-500">({orders.length} 笔订单)</span>
            </h1>
            <p className="text-xs text-slate-500 mt-1">支持实时查询顺丰物流轨迹、AI 极速申请退款或变更未发货收货地址</p>
          </div>

          {/* 状态筛选 Tab */}
          <div className="flex flex-wrap gap-1 bg-white p-1 rounded-xl border border-slate-200 shadow-2xs">
            {[
              { label: '全部', val: 'ALL' },
              { label: '待发货', val: 'PAID' },
              { label: '已发货', val: 'SHIPPED' },
              { label: '已签收', val: 'DELIVERED' },
              { label: '已退款', val: 'REFUNDED' },
            ].map((tab) => (
              <button
                key={tab.val}
                type="button"
                onClick={() => setFilterStatus(tab.val)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
                  filterStatus === tab.val
                    ? 'bg-emerald-600 text-white shadow-2xs'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="bg-white rounded-2xl p-12 border border-slate-200 text-center">
            <div className="text-slate-400 text-xs flex items-center justify-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping" />
              <span>正在获取订单数据...</span>
            </div>
          </div>
        ) : orders.length === 0 ? (
          <div className="bg-white rounded-2xl p-12 border border-slate-200 text-center max-w-xl mx-auto my-8">
            <div className="text-5xl mb-3">📋</div>
            <h2 className="text-base font-bold text-slate-800">暂无相关订单</h2>
            <p className="text-xs text-slate-400 mt-1">您还没有符合该状态筛选的订单记录</p>
            <div className="mt-6">
              <Link
                to="/"
                className="px-5 py-2.5 bg-emerald-600 text-white text-xs font-semibold rounded-xl hover:bg-emerald-500 shadow-xs transition"
              >
                去商城选购
              </Link>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {orders.map((order) => (
              <div
                key={order.orderId}
                className="bg-white rounded-2xl p-5 border border-slate-200 shadow-2xs hover:border-slate-300 transition space-y-4"
              >
                {/* 订单卡片顶部信息 */}
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
                  <div className="flex items-center space-x-3 text-xs">
                    <span className="font-mono font-bold text-slate-800">订单号: {order.orderId}</span>
                    <span className="text-slate-400">|</span>
                    <span className="text-slate-500">
                      下单时间: {order.createdAt ? new Date(order.createdAt).toLocaleString('zh-CN') : '-'}
                    </span>
                  </div>
                  <div>{getStatusBadge(order.status)}</div>
                </div>

                {/* 订单明细项 */}
                <div className="space-y-3">
                  {order.items?.map((item, idx) => (
                    <div key={idx} className="flex items-center space-x-4">
                      <img
                        src={item.imageUrl || 'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=200'}
                        alt={item.title}
                        className="w-16 h-16 rounded-xl object-cover border border-slate-200 shrink-0"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-bold text-slate-900 truncate">{item.title}</div>
                        <div className="text-[11px] text-slate-500 mt-0.5">
                          规格: {item.skuTitle || item.skuCode || '标准规格'}
                        </div>
                        <div className="text-xs font-semibold text-slate-700 mt-1">
                          ¥{Number(item.price).toFixed(2)} × {item.quantity} 件
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* 底部收货人与操作栏 */}
                {(() => {
                  const addrInfo = parseAddress(order.shippingAddress);
                  return (
                    <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
                      <div className="space-y-0.5">
                        <div className="text-slate-600">
                          收货信息: <strong className="text-slate-800">{addrInfo.recipientName}</strong> (
                          {addrInfo.phone})
                        </div>
                        <div className="text-slate-500 text-[11px] truncate max-w-xl">{addrInfo.fullAddress}</div>
                      </div>

                      <div className="flex items-center space-x-2 shrink-0">
                        <div className="mr-3 text-right">
                          <span className="text-slate-500 text-[11px]">实付金额:</span>
                          <strong className="text-emerald-700 text-sm ml-1">
                            ¥{Number(order.totalAmount).toFixed(2)}
                          </strong>
                        </div>

                        <button
                          type="button"
                          onClick={() => {
                            setSelectedDetailOrder(order);
                            setIsOrderDetailModalOpen(true);
                          }}
                          className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 font-semibold text-slate-700 cursor-pointer shadow-2xs"
                        >
                          详情
                        </button>

                        <button
                          type="button"
                          onClick={() => {
                            setSelectedLogisticsOrder(order);
                            setIsLogisticsModalOpen(true);
                          }}
                          className="px-3 py-1.5 rounded-lg border border-emerald-200 bg-emerald-50 hover:bg-emerald-100 font-semibold text-emerald-800 cursor-pointer shadow-2xs"
                        >
                          🚚 物流跟踪
                        </button>
                      </div>
                    </div>
                  );
                })()}
              </div>
            ))}
          </div>
        )}
      </main>

      <OrderDetailModal
        isOpen={isOrderDetailModalOpen}
        onClose={() => setIsOrderDetailModalOpen(false)}
        order={selectedDetailOrder}
        onOpenLogistics={(order) => {
          setSelectedLogisticsOrder(order);
          setIsLogisticsModalOpen(true);
        }}
        onOpenChatWithOrder={() => {}}
      />

      <LogisticsModal
        isOpen={isLogisticsModalOpen}
        onClose={() => setIsLogisticsModalOpen(false)}
        order={selectedLogisticsOrder}
        onOpenChatWithOrder={() => {}}
      />
    </div>
  );
}
