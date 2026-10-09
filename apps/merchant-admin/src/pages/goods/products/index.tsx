import { type Spu, api } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { SpuCreateDialog } from './components/spu-create-form';
import { SpuTable } from './components/spu-table';

// 商品目录管理页(薄编排):页头新增入口 / SPU 表(弹窗编辑+上下架+删除)/
// SKU 子表,按功能拆在同目录 components/ 下;数据操作收口 lib/api.ts。
export default function ProductsPage({ focusCode }: { focusCode?: string } = {}) {
  const [spus, setSpus] = useState<Spu[]>([]);
  const [msg, setMsg] = useState('');
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setSpus((await api.products.list()).spus || []);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      {msg && <div className="rounded-lg border border-zinc-200 bg-white px-4 py-2 text-xs text-zinc-600">{msg}</div>}
      <SpuTable spus={spus} onMsg={setMsg} onChanged={() => void load()} onCreate={() => setCreating(true)} />
      {creating && (
        <SpuCreateDialog
          onMsg={setMsg}
          onClose={() => {
            setCreating(false);
            void load();
          }}
        />
      )}
    </div>
  );
}
