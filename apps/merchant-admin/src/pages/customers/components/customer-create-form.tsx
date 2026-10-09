import { api } from '@/lib/api';
import { useState } from 'react';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input, Label } from 'ui';

interface Props {
  onMsg: (m: string) => void;
  onClose: () => void;
}

/** 新增客户弹窗(商户库直写)。 */
export function CustomerCreateDialog({ onMsg, onClose }: Props) {
  const [newCust, setNewCust] = useState({ name: '', phone: '' });

  async function create() {
    const name = newCust.name.trim();
    const phone = newCust.phone.trim();
    if (!name || !phone) return;
    const body = await api.customers.create({ name, phone });
    onMsg(body.success ? `✓ 已新增客户 ${body.customerId}` : `失败:${body.message}`);
    if (body.success) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">新增客户</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">商户库直写;姓名 + 电话必填</p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
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
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!newCust.name.trim() || !newCust.phone.trim()}
            onClick={() => void create()}
            className="text-xs font-bold cursor-pointer"
          >
            新增
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
