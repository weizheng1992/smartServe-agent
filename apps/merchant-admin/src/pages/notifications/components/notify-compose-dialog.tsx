import { FormDialogShell } from '@/components/form-dialog-shell';
import { SearchableSelect } from '@/components/searchable-select';
import { api, errMsgOf } from '@/lib/api';
import { useState } from 'react';
import { Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Textarea } from 'ui';

interface Props {
  /** 非空 = 客户详情抽屉单发模式:范围锁定该顾客、不显范围选择器。 */
  lockedCustomer?: { id: string; name: string } | null;
  /** 顾客选项(定向模式选择器;页级一次拉取传入,弹窗内不重复拉)。 */
  customers: Array<{ customerId: string; name: string }>;
  onClose: () => void;
  onMsg: (msg: string) => void;
}

/** 撰写/发送弹窗(模块页广播 + 客户详情单发共用一表 —— spec D8):标题 ≤50
 *  必填、正文 ≤500 必填,前后端同闸;范围 = 全部顾客 | 定向单客(Radix Select
 *  空值两律:占位符走受控 '',选项无空串)。频控(单员工单日广播 ≤20)是服务
 *  端闸,超限业务错误文案留窗内(FormDialogShell 契约,窗不关)。 */
export function NotifyComposeDialog({ lockedCustomer, customers, onClose, onMsg }: Props) {
  const [targetType, setTargetType] = useState<'all' | 'customer'>(lockedCustomer ? 'customer' : 'all');
  const [customerId, setCustomerId] = useState('');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  // 锁定模式的顾客 id 不走选择器 state(无 onChange 可写),提交时单点合成
  const effCustomerId = lockedCustomer?.id ?? customerId;

  async function submit(): Promise<string | null> {
    const t = title.trim();
    const b = body.trim();
    if (!t) return '标题必填';
    if (t.length > 50) return '标题不超过 50 字';
    if (!b) return '正文必填';
    if (b.length > 500) return '正文不超过 500 字';
    if (targetType === 'customer' && !effCustomerId) return '定向发送必须选择顾客';
    const res = (await api.notifications.send({
      targetType,
      customerId: targetType === 'customer' ? effCustomerId : undefined,
      title: t,
      body: b,
    })) as { success?: boolean; message?: string };
    if (!res?.success) return errMsgOf(res, '发送失败');
    const scope =
      targetType === 'all'
        ? '全部顾客'
        : lockedCustomer?.name || customers.find((c) => c.customerId === customerId)?.name || customerId;
    onMsg(`已发送「${t}」→ ${scope}`);
    return null;
  }

  return (
    <FormDialogShell
      title="发送站内消息"
      subtitle="顾客在商城消息中心收到;广播每员工每日限 20 条"
      maxWidth="max-w-md"
      submitLabel="发送"
      submitDisabled={!title.trim() || !body.trim()}
      onSubmit={submit}
      onClose={onClose}
    >
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label>发送范围</Label>
          {lockedCustomer ? (
            <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-700">
              定向单客:{lockedCustomer.name}({lockedCustomer.id})
            </div>
          ) : (
            <Select value={targetType} onValueChange={(v) => setTargetType(v as 'all' | 'customer')}>
              <SelectTrigger aria-label="发送范围">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部顾客(广播)</SelectItem>
                <SelectItem value="customer">定向单客</SelectItem>
              </SelectContent>
            </Select>
          )}
        </div>

        {targetType === 'customer' && !lockedCustomer && (
          <div className="space-y-1.5">
            <Label>选择顾客</Label>
            <SearchableSelect
              value={customerId}
              onValueChange={setCustomerId}
              options={customers.map((c) => ({ value: c.customerId, label: `${c.name}(${c.customerId})` }))}
              placeholder="— 选择顾客 —"
              ariaLabel="选择顾客"
            />
          </div>
        )}

        <div className="space-y-1.5">
          <Label htmlFor="notify-title">标题(必填,≤50 字)</Label>
          <Input
            id="notify-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={50}
            placeholder="如:本周新品上市"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="notify-body">正文(必填,≤500 字)</Label>
          <Textarea
            id="notify-body"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            maxLength={500}
            rows={4}
            placeholder="公告正文…"
          />
        </div>
      </div>
    </FormDialogShell>
  );
}
