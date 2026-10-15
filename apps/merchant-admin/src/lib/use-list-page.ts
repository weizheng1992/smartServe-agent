import { errMsgOf } from '@/lib/api';
import { useCallback, useEffect, useRef, useState } from 'react';

/** 列表页摆设单点(2026-10-15 候选④):rows + msg 横幅 + 挂载拉取 + 稳定 reload。
 *  此前 9 个 index 页逐字重复同一 load/reload/msg 摆设 ≈18 行/页,且 customers
 *  的「关闭后 reload 与详情抽屉竞态 → 无限重取循环 + 陈旧闭包重开抽屉」修法只
 *  落在那一页 —— reload 恒稳定(依赖空数组 + loader 走 ref),该修法天然只写一次。
 *
 *  loader 返回行数组;多资源页(roles/promotions/owner-mappings 等)在 loader
 *  闭包内就地 set 次级状态(effect/tree/categories…)。loader 抛错 → setMsg
 *  「加载失败:…」,rows 保持上一次(诚实横幅,不塌空)。close-reload 不进
 *  hook:页面 onClose 里显式调 reload()(「关闭即刷新」是页面意图,非隐式行为)。 */
export function useListPage<T>(loader: () => Promise<T[]>) {
  const [rows, setRows] = useState<T[]>([]);
  const [msg, setMsg] = useState('');
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async () => {
    try {
      setRows(await loaderRef.current());
    } catch (err) {
      setMsg(`加载失败:${errMsgOf(err, String(err))}`);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { rows, msg, setMsg, reload };
}
