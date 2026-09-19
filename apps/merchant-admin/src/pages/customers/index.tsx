import { useCallback, useEffect, useState } from 'react';
import { api, type Customer } from '@/lib/api';
import { CustomerCreateForm } from './components/customer-create-form';
import { CustomerTable } from './components/customer-table';
import { CustomerDetailDrawer } from './components/customer-detail-drawer';

// 客户管理:新增 + 会员级编辑 + 删除 + 详情抽屉(地址/关联券/关联订单跳转)。
// 页面只做编排;表单/列表/详情拆在同目录 components/ 下。
export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [msg, setMsg] = useState('');
  const [detail, setDetail] = useState<Customer | null>(null);

  const load = useCallback(async () => {
    try {
      const list = (await api.customers.list()).customers || [];
      setCustomers(list);
      // 详情开着时同步其最新数据(改会员级/删除后不显示陈旧信息)
      if (detail) setDetail(list.find((c) => c.customer_id === detail.customer_id) || null);
    } catch (err) {
      setMsg(String(err));
    }
  }, [detail]);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <CustomerCreateForm onMsg={setMsg} onCreated={() => void load()} />
      <CustomerTable customers={customers} onMsg={setMsg} onChanged={() => void load()} onDetail={setDetail} />
      {msg && <div className="px-4 py-2 text-[11px] text-zinc-500">{msg}</div>}
      {detail && <CustomerDetailDrawer customer={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}
