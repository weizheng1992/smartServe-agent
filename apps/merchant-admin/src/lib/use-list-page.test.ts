import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useListPage } from './use-list-page';

// 列表页摆设单点钉(候选④):挂载拉取/稳定 reload/失败横幅不塌空 ——
// customers 的 close-race 修法(恒稳定引用)从此只写一次。

describe('useListPage(列表页摆设单点)', () => {
  it('挂载即拉取;reload 重取并替换 rows', async () => {
    let data = ['a', 'b'];
    const loader = vi.fn(async () => data);
    const { result } = renderHook(() => useListPage<string>(loader));
    await waitFor(() => expect(result.current.rows).toEqual(['a', 'b']));
    const reloadRef = result.current.reload;
    data = ['c'];
    await act(() => result.current.reload());
    expect(result.current.rows).toEqual(['c']);
    expect(result.current.reload).toBe(reloadRef); // 恒稳定引用(close-reload 竞态免疫)
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('loader 抛错:msg 横幅「加载失败:…」,rows 保持上一次(诚实不塌空)', async () => {
    const loader = vi.fn(async () => ['a']);
    const { result } = renderHook(() => useListPage<string>(loader));
    await waitFor(() => expect(result.current.rows).toEqual(['a']));
    loader.mockRejectedValueOnce(new Error('gateway down'));
    await act(() => result.current.reload());
    expect(result.current.msg).toContain('加载失败');
    expect(result.current.msg).toContain('gateway down');
    expect(result.current.rows).toEqual(['a']);
  });

  it('reload 引用跨 render 稳定:作为 onClose/onChanged 回调不会触发 effect 重跑', async () => {
    const loader = vi.fn(async () => ['x']);
    const { result, rerender } = renderHook(() => useListPage<string>(loader));
    await waitFor(() => expect(result.current.rows).toEqual(['x']));
    const before = result.current.reload;
    rerender();
    expect(result.current.reload).toBe(before);
    expect(loader).toHaveBeenCalledTimes(1); // 重渲染不重取
  });
});
