import { FormDialogShell } from '@/components/form-dialog-shell';
import { api, errMsgOf } from '@/lib/api';
import { useState } from 'react';
import { Input, Label } from 'ui';

interface Props {
  onMsg: (m: string) => void;
  onClose: () => void;
}

/** 新增客户弹窗(商户库直写)。 */
export function CustomerCreateDialog({ onMsg, onClose }: Props) {
  const [newCust, setNewCust] = useState({ name: '', phone: '' });
  const ready = newCust.name.trim() !== '' && newCust.phone.trim() !== '';

  return (
    <FormDialogShell
      title="新增客户"
      subtitle="商户库直写;姓名 + 电话必填"
      submitLabel="新增"
      submitDisabled={!ready}
      onClose={onClose}
      onSubmit={async () => {
        const body = await api.customers.create({ name: newCust.name.trim(), phone: newCust.phone.trim() });
        if (!body.success) return errMsgOf(body);
        onMsg(`✓ 已新增客户 ${body.customerId}`);
        return null;
      }}
    >
      <div>
        <Label htmlFor="cust-name" className="mb-1.5 block text-zinc-700">
          姓名
        </Label>
        <Input
          id="cust-name"
          className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
          placeholder="客户姓名"
          value={newCust.name}
          onChange={(e) => setNewCust({ ...newCust, name: e.target.value })}
        />
      </div>
      <div>
        <Label htmlFor="cust-phone" className="mb-1.5 block text-zinc-700">
          电话
        </Label>
        <Input
          id="cust-phone"
          className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
          placeholder="联系电话"
          value={newCust.phone}
          onChange={(e) => setNewCust({ ...newCust, phone: e.target.value })}
        />
      </div>
    </FormDialogShell>
  );
}
