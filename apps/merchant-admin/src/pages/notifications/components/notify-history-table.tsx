import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type MerchantNotification } from '@/lib/api';
import { Badge } from 'ui';

/** 范围回显(诚实降级):广播 → 全部顾客;定向 → 顾客名,缺名退 customerId,
 *  双缺「—」—— 严禁编造(spec 数据诚实律)。 */
export function targetLabel(n: MerchantNotification): string {
  if (n.targetType === 'all') return '全部顾客';
  return n.customerName || n.customerId || '—';
}

interface Props {
  rows: MerchantNotification[];
}

/** 已发历史表(只读审计,spec F2):时间/标题/范围/发送量/操作人。
 *  刻意无已读回执列 —— 服务端就不发(D6 商户不见回执),前端无处可显。 */
export function NotifyHistoryTable({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-zinc-200 px-4 py-10 text-center text-xs text-zinc-400">
        暂无发送记录
      </div>
    );
  }
  return (
    <div className="overflow-auto rounded-lg border border-zinc-200 bg-white">
      <DenseTable>
        <DenseTableHeader>
          <DenseTableRow>
            <DenseTableHead>时间</DenseTableHead>
            <DenseTableHead>标题</DenseTableHead>
            <DenseTableHead>范围</DenseTableHead>
            <DenseTableHead className="text-right">发送量</DenseTableHead>
            <DenseTableHead>操作人</DenseTableHead>
          </DenseTableRow>
        </DenseTableHeader>
        <DenseTableBody>
          {rows.map((n) => (
            <DenseTableRow key={n.id}>
              <DenseTableCell className="whitespace-nowrap text-zinc-500">
                {/* 两套钟律(server-gateway.md §2.4):createdAt 是 aware UTC ISO,
                    截串直显会复刻「显示早 8 小时」实弹 —— 必须经 Date 解析转本地墙钟 */}
                {n.createdAt && !Number.isNaN(new Date(n.createdAt).getTime())
                  ? new Date(n.createdAt).toLocaleString()
                  : '—'}
              </DenseTableCell>
              <DenseTableCell className="max-w-64 font-medium text-zinc-900">{n.title}</DenseTableCell>
              <DenseTableCell>
                {n.targetType === 'all' ? (
                  <Badge variant="secondary">全部顾客</Badge>
                ) : (
                  <Badge variant="outline">定向 · {targetLabel(n)}</Badge>
                )}
              </DenseTableCell>
              <DenseTableCell className="text-right tabular-nums">{n.recipientCount}</DenseTableCell>
              <DenseTableCell className="text-zinc-500">{n.createdBy || '—'}</DenseTableCell>
            </DenseTableRow>
          ))}
        </DenseTableBody>
      </DenseTable>
    </div>
  );
}
