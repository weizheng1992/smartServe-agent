'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import React, { useEffect, useState } from 'react';
import type { ThirdPartyOrder } from 'types';
import { StorefrontHeader } from '../../components/navbar/StorefrontHeader';
import { LogisticsModal } from '../../components/orders/LogisticsModal';

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

export default function SingleOrderDetailPage() {
  const params = useParams();
  const orderId = params?.id as string;

  const [order, setOrder] = useState<ThirdPartyOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLogisticsOpen, setIsLogisticsOpen] = useState(false);

  useEffect(() => {
    if (!orderId) return;
    const fetchDetail = async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/store/orders/${orderId}`);
        const data = await res.json();
        if (data.success && data.order) {
          setOrder(data.order);
        } else {
          setError(data.error || '未找到该订单');
        }
      } catch {
        setError('获取订单详情失败');
      } finally {
        setLoading(false);
      }
    };
    fetchDetail();
  }, [orderId]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <StorefrontHeader />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-slate-500 text-xs flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping" />
            <span>正在加载订单明细...</span>
          </div>
        </div>
      </div>
    );
  }

  if (error || !order) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <StorefrontHeader />
        <div className="max-w-xl mx-auto my-12 p-8 bg-white rounded-2xl border border-slate-200 text-center">
          <div className="text-4xl mb-2">📋</div>
          <h2 className="text-base font-bold text-slate-800">订单未找到</h2>
          <p className="text-xs text-slate-500 mt-1">{error || '该订单不存在或已被删除'}</p>
          <div className="mt-6">
            <Link
              href="/orders"
              className="px-4 py-2 bg-emerald-600 text-white rounded-lg text-xs font-semibold hover:bg-emerald-500 transition"
            >
              返回我的订单中心
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <StorefrontHeader />

      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-8 flex-1 w-full space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center space-x-2 text-xs text-slate-500 mb-1">
              <Link href="/orders" className="hover:text-emerald-700">
                我的订单
              </Link>
              <span>/</span>
              <span className="font-mono text-slate-700">{order.orderId}</span>
            </div>
            <h1 className="text-xl font-bold text-slate-900">
              订单详情 · <span className="font-mono text-emerald-700">{order.orderId}</span>
            </h1>
          </div>
          <button
            type="button"
            onClick={() => setIsLogisticsOpen(true)}
            className="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-xl shadow-xs transition cursor-pointer"
          >
            🚚 查看实时顺丰物流
          </button>
        </div>

        {/* 订单明细清单 */}
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-2xs space-y-4">
          <h2 className="text-sm font-bold text-slate-800 border-b border-slate-100 pb-3">商品清单与规格</h2>
          <div className="divide-y divide-slate-100">
            {order.items?.map((item, idx) => (
              <div key={idx} className="py-3 flex items-center space-x-4">
                <img
                  src={item.imageUrl || 'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=200'}
                  alt={item.title}
                  className="w-16 h-16 rounded-xl object-cover border border-slate-200 shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-bold text-slate-900">{item.title}</div>
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

          <div className="pt-3 border-t border-slate-100 flex justify-between items-baseline text-xs">
            <span className="text-slate-500">实付总金额</span>
            <span className="text-lg font-extrabold text-emerald-700">¥{Number(order.totalAmount).toFixed(2)}</span>
          </div>
        </div>

        {/* 配送信息 */}
        {(() => {
          const addrInfo = parseAddress(order.shippingAddress);
          return (
            <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-2xs space-y-3">
              <h2 className="text-sm font-bold text-slate-800 border-b border-slate-100 pb-3">📍 配送收货信息</h2>
              <div className="text-xs space-y-1">
                <div className="text-slate-700">
                  收货人: <strong className="text-slate-900">{addrInfo.recipientName}</strong> (
                  <span className="font-mono">{addrInfo.phone}</span>)
                </div>
                <div className="text-slate-600 leading-relaxed">{addrInfo.fullAddress}</div>
              </div>
            </div>
          );
        })()}
      </main>

      <LogisticsModal
        isOpen={isLogisticsOpen}
        onClose={() => setIsLogisticsOpen(false)}
        order={order}
        onOpenChatWithOrder={() => {}}
      />
    </div>
  );
}
