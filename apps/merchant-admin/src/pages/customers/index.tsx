import { type Customer, api } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { CustomerCreateDialog } from './components/customer-create-form';
import { CustomerDetailDrawer } from './components/customer-detail-drawer';
import { CustomerTable } from './components/customer-table';

// 客户管理:新增(弹窗)+ 会员级编辑 + 删除 + 详情抽屉(地址/关联券/关联订单跳转)。
// 页面只做编排;表单/列表/详情拆在同目录 components/ 下。
export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [msg, setMsg] = useState('');
  const [detail, setDetail] = useState<Customer | null>(null);
  const [creating, setCreating] = useState(false);

  // load 稳定引用(依赖空数组):详情数据同步用函数式 setState 读取最新
  // detail —— 此前依赖 [detail] 且 setDetail(新对象) 会形成「无限重取循环 +
  // 陈旧闭包重开抽屉」(回归:详情页关不掉)。
  const load = useCallback(async () => {
    try {
      const list = (await api.customers.list()).customers || [];
      setCustomers(list);
      setDetail((cur) => (cur ? list.find((c) => c.customer_id === cur.customer_id) || null : cur));
    } catch (err) {
      setMsg(String(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">客户管理</div>
          <div className="mt-0.5 text-xs text-zinc-400">会员档案、消费与关联订单</div>
        </div>
        <Button size="sm" onClick={() => setCreating(true)}>
          + 新增客户
        </Button>
      </div>
      <CustomerTable customers={customers} onMsg={setMsg} onChanged={() => void load()} onDetail={setDetail} />
      {creating && (
        <CustomerCreateDialog
          onMsg={setMsg}
          onClose={() => {
            setCreating(false);
            void load();
          }}
        />
      )}
      {msg && <div className="px-4 py-2 text-[11px] text-zinc-500">{msg}</div>}
      {detail && <CustomerDetailDrawer customer={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}
