import { type Customer, api } from '@/lib/api';
import { useListPage } from '@/lib/use-list-page';
import { useState } from 'react';
import { Button } from 'ui';
import { CustomerCreateDialog } from './components/customer-create-form';
import { CustomerDetailDrawer } from './components/customer-detail-drawer';
import { CustomerTable } from './components/customer-table';

// 客户管理:新增(弹窗)+ 会员级编辑 + 删除 + 详情抽屉(地址/关联券/关联订单跳转)。
// 页面只做编排;表单/列表/详情拆在同目录 components/ 下。
export default function CustomersPage() {
  const [detail, setDetail] = useState<Customer | null>(null);
  const [creating, setCreating] = useState(false);
  // 详情抽屉开着时同步其行数据:函数式 setState 读最新 detail;reload 恒稳定
  // (useListPage)——「无限重取循环 + 陈旧闭包重开抽屉」的竞态修法单点在 hook。
  const {
    rows: customers,
    msg,
    setMsg,
    reload,
  } = useListPage<Customer>(async () => {
    const list = (await api.customers.list()).customers || [];
    setDetail((cur) => (cur ? list.find((c) => c.customer_id === cur.customer_id) || null : cur));
    return list;
  });

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
      <CustomerTable customers={customers} onMsg={setMsg} onChanged={() => void reload()} onDetail={setDetail} />
      {creating && (
        <CustomerCreateDialog
          onMsg={setMsg}
          onClose={() => {
            setCreating(false);
            void reload();
          }}
        />
      )}
      {msg && <div className="px-4 py-2 text-[11px] text-zinc-500">{msg}</div>}
      {detail && <CustomerDetailDrawer customer={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}
