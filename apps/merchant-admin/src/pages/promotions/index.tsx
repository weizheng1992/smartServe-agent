import { type PromoEffect, type Promotion, api } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { EffectCards } from './components/effect-cards';
import { PromoCreateForm } from './components/promo-form';
import { PromoTable } from './components/promo-table';

// 优惠活动页(薄编排):效果速览 / 新建 / 核销与活动表,组件在同目录 components/。
export default function PromotionsPage() {
  const [promotions, setPromotions] = useState<Promotion[]>([]);
  const [effect, setEffect] = useState<PromoEffect | null>(null);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    try {
      const body = await api.promotions.list();
      setPromotions(body.promotions || []);
      setEffect(body.effect || null);
    } catch (err) {
      setMsg(String(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <EffectCards effect={effect} />
      <PromoCreateForm msg={msg} onMsg={setMsg} onCreated={() => void load()} />
      <PromoTable promotions={promotions} onMsg={setMsg} onChanged={() => void load()} />
    </div>
  );
}
