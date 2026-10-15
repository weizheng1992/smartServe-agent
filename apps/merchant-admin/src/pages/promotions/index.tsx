import { type PromoEffect, type Promotion, type Spu, api } from '@/lib/api';
import { useListPage } from '@/lib/use-list-page';
import { useEffect, useState } from 'react';
import { Button } from 'ui';
import { EffectCards } from './components/effect-cards';
import { PromoFormDialog } from './components/promo-dialog';
import { PromoTable } from './components/promo-table';

// 优惠活动页(薄编排):页头新建入口 + 效果速览 + 活动表;新建/编辑统一走
// PromoFormDialog 弹窗(页级单实例,promo=null 新建 / 非空编辑),组件在同目录 components/。
export default function PromotionsPage() {
  const [effect, setEffect] = useState<PromoEffect | null>(null);
  const [spus, setSpus] = useState<Spu[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Promotion | null>(null);

  // 次级资源(效果速览)在 loader 闭包内就地 set(useListPage 候选④)
  const {
    rows: promotions,
    msg,
    setMsg,
    reload,
  } = useListPage<Promotion>(async () => {
    const body = await api.promotions.list();
    setEffect(body.effect || null);
    return body.promotions || [];
  });

  useEffect(() => {
    // SPU 选项(弹窗范围选择)与表格范围回显共用一次拉取
    void api.products.list().then((b) => setSpus(b.spus || []));
  }, []);

  const spuTitles = Object.fromEntries(spus.map((s) => [s.spu_code, s.title]));

  function openCreate() {
    setEditing(null);
    setDialogOpen(true);
  }
  function openEdit(p: Promotion) {
    setEditing(p);
    setDialogOpen(true);
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">优惠活动</div>
          <div className="mt-0.5 text-xs text-zinc-400">满减 / 折扣 / 券的创建、发放与核销</div>
        </div>
        <Button size="sm" onClick={openCreate}>
          + 新建活动
        </Button>
      </div>
      {msg && <div className="rounded-lg border border-zinc-200 bg-white px-4 py-2 text-xs text-zinc-600">{msg}</div>}
      <EffectCards effect={effect} />
      <PromoTable
        promotions={promotions}
        spuTitles={spuTitles}
        onMsg={setMsg}
        onChanged={() => void reload()}
        onEdit={openEdit}
      />
      {/* 条件挂载(候选④统一协议):新建置 dialogOpen,编辑置 editing;卸载即重置 */}
      {(dialogOpen || editing) && (
        <PromoFormDialog
          promo={editing}
          spus={spus}
          onClose={() => {
            setDialogOpen(false);
            setEditing(null);
          }}
          onMsg={(m) => {
            setMsg(m);
            void reload();
          }}
        />
      )}
    </div>
  );
}
