import { type Spu, api } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { SpuCreateForm } from './components/spu-create-form';
import { SpuTable } from './components/spu-table';

// 商品目录管理页(薄编排):新增表单 / SPU 表(行内编辑+上下架+删除)/
// SKU 子表,按功能拆在同目录 components/ 下;数据操作收口 lib/api.ts。
export default function ProductsPage({ focusCode }: { focusCode?: string } = {}) {
  const [spus, setSpus] = useState<Spu[]>([]);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    setSpus((await api.products.list()).spus || []);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <SpuCreateForm msg={msg} onMsg={setMsg} onCreated={() => void load()} />
      <SpuTable spus={spus} onMsg={setMsg} onChanged={() => void load()} />
    </div>
  );
}
