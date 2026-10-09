import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect } from 'vitest';

// jsdom 里驱动 Radix Select(ui 的 Select 全家)的统一 helper。
// Radix 开层走 pointerdown 路径(依赖 setup.ts 的 pointer capture 桩);
// 弹层经 Portal 挂 document.body,screen 可直接查询 role=option。

type Trigger = HTMLElement | string;

async function openAndPick(trigger: Trigger, option: string | RegExp) {
  const el = typeof trigger === 'string' ? screen.getByLabelText(trigger) : trigger;
  fireEvent.pointerDown(el, { button: 0, pointerType: 'mouse' });
  fireEvent.click(el, { button: 0, pointerType: 'mouse' });
  // 弹层为异步挂载(findByRole 轮询);若 pointer 路径在某版本失稳,
  // 此处会超时——兜底改键盘路径(fireEvent.keyDown(el, { key: 'ArrowDown' }))
  const item = await screen.findByRole('option', { name: option });
  fireEvent.click(item);
  // 等弹层收起,避免同用例内两次选择时 option 残留互相命中
  await waitFor(() => expect(screen.queryByRole('option')).toBeNull());
}

/** 按 label(或既有 trigger 元素)打开 Select 并点选指定文案/正则的 option。 */
export function selectRadixOption(trigger: Trigger, option: string | RegExp): Promise<void> {
  return openAndPick(trigger, option);
}
