'use client';

import Link from 'next/link';
import React, { useEffect, useState } from 'react';
import { Button, Input } from 'ui';
import type { CustomerAddress } from '../components/address/AddressModal';
import { StorefrontHeader } from '../components/navbar/StorefrontHeader';

export default function AddressesPage() {
  const [addresses, setAddresses] = useState<CustomerAddress[]>([]);
  const [loading, setLoading] = useState(true);

  // 表单状态
  const [recipientName, setRecipientName] = useState('');
  const [phone, setPhone] = useState('');
  const [province, setProvince] = useState('北京市');
  const [city, setCity] = useState('北京市');
  const [district, setDistrict] = useState('海淀区');
  const [detailAddress, setDetailAddress] = useState('');
  const [tag, setTag] = useState('公司');
  const [isDefault, setIsDefault] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fetchAddresses = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/store/addresses?customerId=CUST-8801');
      const data = await res.json();
      if (data.success && data.addresses) {
        setAddresses(data.addresses);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAddresses();
  }, []);

  const handleAddAddress = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!recipientName || !phone || !detailAddress) {
      alert('请填写完整的收货人、联系电话和详细地址');
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch('/api/store/addresses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customerId: 'CUST-8801',
          recipientName,
          phone,
          province,
          city,
          district,
          detailAddress,
          tag,
          isDefault,
        }),
      });
      const data = await res.json();
      if (data.success && data.address) {
        setAddresses((prev) => [data.address, ...prev]);
        setRecipientName('');
        setPhone('');
        setDetailAddress('');
        setIsDefault(false);
        setSuccessMsg('新地址已成功保存！');
        setTimeout(() => setSuccessMsg(null), 3000);
      }
    } catch {
      alert('保存地址失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <StorefrontHeader addressCount={addresses.length} />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full">
        <div className="mb-6">
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 flex items-center space-x-2">
            <span>📍 收货地址簿管理</span>
            <span className="text-xs font-normal text-slate-500">({addresses.length} 个地址)</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            设置您的常用配送收货地址，下单快速调用；也可通过 AI 智能客服秒级同步未发货订单！
          </p>
        </div>

        {successMsg && (
          <div className="mb-6 p-4 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-semibold flex items-center space-x-2 animate-in fade-in">
            <span>✅</span>
            <span>{successMsg}</span>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* 左侧地址列表 */}
          <div className="lg:col-span-7 space-y-3">
            <h2 className="text-sm font-bold text-slate-800 mb-2">已保存的收货地址</h2>
            {loading ? (
              <div className="bg-white rounded-2xl p-12 border border-slate-200 text-center">
                <div className="text-slate-400 text-xs flex items-center justify-center space-x-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping" />
                  <span>正在加载地址列表...</span>
                </div>
              </div>
            ) : addresses.length === 0 ? (
              <div className="bg-white rounded-2xl p-8 border border-slate-200 text-center">
                <div className="text-3xl mb-2">📍</div>
                <div className="text-xs text-slate-500">暂无收货地址，请在右侧表单新增</div>
              </div>
            ) : (
              addresses.map((addr) => (
                <div
                  key={addr.id}
                  className={`bg-white rounded-2xl p-5 border shadow-2xs space-y-2 transition ${
                    addr.isDefault ? 'border-emerald-500 bg-emerald-50/10' : 'border-slate-200'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                      <span className="font-bold text-xs text-slate-900">{addr.recipientName}</span>
                      <span className="text-xs text-slate-500 font-mono">{addr.phone}</span>
                      {addr.tag && (
                        <span className="px-2 py-0.2 rounded text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                          {addr.tag}
                        </span>
                      )}
                    </div>
                    {addr.isDefault && (
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-100 text-emerald-800">
                        默认地址
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-600 leading-relaxed">{addr.fullAddress}</div>
                </div>
              ))
            )}
          </div>

          {/* 右侧新增地址表单 */}
          <div className="lg:col-span-5">
            <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-2xs space-y-4">
              <h2 className="text-sm font-bold text-slate-800 border-b border-slate-100 pb-3">➕ 新增常用收货地址</h2>

              <form onSubmit={handleAddAddress} className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">收货人姓名</label>
                  <Input
                    type="text"
                    placeholder="如：张伟"
                    value={recipientName}
                    onChange={(e) => setRecipientName(e.target.value)}
                    required
                    className="text-xs"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">联系电话</label>
                  <Input
                    type="tel"
                    placeholder="如：13800138000"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    required
                    className="text-xs"
                  />
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">省份</label>
                    <Input
                      type="text"
                      value={province}
                      onChange={(e) => setProvince(e.target.value)}
                      className="text-xs"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">城市</label>
                    <Input type="text" value={city} onChange={(e) => setCity(e.target.value)} className="text-xs" />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">区县</label>
                    <Input
                      type="text"
                      value={district}
                      onChange={(e) => setDistrict(e.target.value)}
                      className="text-xs"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">详细街道门牌地址</label>
                  <Input
                    type="text"
                    placeholder="如：中关村南大街1号院8号楼1201室"
                    value={detailAddress}
                    onChange={(e) => setDetailAddress(e.target.value)}
                    required
                    className="text-xs"
                  />
                </div>

                <div className="flex items-center justify-between pt-1">
                  <div className="flex items-center space-x-2">
                    {['家', '公司', '学校'].map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setTag(t)}
                        className={`px-2.5 py-1 rounded text-xs border cursor-pointer ${
                          tag === t
                            ? 'bg-emerald-50 text-emerald-800 border-emerald-300 font-bold'
                            : 'bg-white text-slate-600 border-slate-200'
                        }`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>

                  <label className="flex items-center space-x-1.5 text-xs text-slate-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isDefault}
                      onChange={(e) => setIsDefault(e.target.checked)}
                      className="w-3.5 h-3.5 text-emerald-600 rounded"
                    />
                    <span>设为默认地址</span>
                  </label>
                </div>

                <div className="pt-3">
                  <Button
                    type="submit"
                    disabled={submitting}
                    className="w-full py-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-xs"
                  >
                    {submitting ? '正在保存...' : '保存收货地址'}
                  </Button>
                </div>
              </form>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
