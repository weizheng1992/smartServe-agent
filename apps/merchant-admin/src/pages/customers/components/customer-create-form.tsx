import { api } from '@/lib/api';
import { useState } from 'react';
import { Button } from 'ui';

interface Props {
  onMsg: (m: string) => void;
  onCreated: () => void;
}

/** 新增客户(商户库直写)。 */
export function CustomerCreateForm({ onMsg, onCreated }: Props) {
  const [newCust, setNewCust] = useState({ name: '', phone: '' });

  async function create() {
    const name = newCust.name.trim();
    const phone = newCust.phone.trim();
    if (!name || !phone) return;
    const body = await api.customers.create({ name, phone });
    onMsg(body.success ? `✓ 已新增客户 ${body.customerId}` : `失败:${body.message}`);
    if (body.success) {
      setNewCust({ name: '', phone: '' });
      onCreated();
    }
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="text-sm font-medium">新增客户</div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <input
          className="w-32 rounded-lg border border-zinc-300 px-3 py-2"
          placeholder="姓名"
          value={newCust.name}
          onChange={(e) => setNewCust({ ...newCust, name: e.target.value })}
        />
        <input
          className="w-40 rounded-lg border border-zinc-300 px-3 py-2"
          placeholder="电话"
          value={newCust.phone}
          onChange={(e) => setNewCust({ ...newCust, phone: e.target.value })}
        />
        <Button size="sm" disabled={!newCust.name || !newCust.phone} onClick={() => void create()}>
          新增
        </Button>
      </div>
    </div>
  );
}
