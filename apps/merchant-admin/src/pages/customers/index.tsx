import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { CustomerCreateForm } from './components/customer-create-form';
import { CustomerTable, type Customer } from './components/customer-table';

// 客户管理:新增 + 会员级编辑 + 删除(有订单客户不可删,服务端护栏)。
// 页面只做编排;新增表单与客户表拆在同目录 components/ 下。
export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    try {
      setCustomers((await api.customers.list()).customers || []);
    } catch (err) {
      setMsg(String(err));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <CustomerCreateForm onMsg={setMsg} onCreated={() => void load()} />
      <CustomerTable customers={customers} onMsg={setMsg} onChanged={() => void load()} />
      {msg && <div className="px-4 py-2 text-[11px] text-zinc-500">{msg}</div>}
    </div>
  );
}
