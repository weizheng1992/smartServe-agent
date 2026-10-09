import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

// vitest globals 关闭时 RTL 不自动清理,统一在每个用例后卸载
afterEach(() => cleanup());
// 集成用例直连真实网关,并发下往返可能超秒级
configure({ asyncUtilTimeout: 8000 });

// jsdom 缺省没有 matchMedia(SWC React 组件偶有媒体查询侦测),补桩防噪
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// Radix Select 开弹层依赖 pointer capture 与滚动定位,jsdom(30.x)缺这三者
// (PointerEvent 构造器原生已有);统一在此补桩,配套 helper 见 ./radix-select.ts
if (typeof window !== 'undefined') {
  const proto = window.HTMLElement.prototype as unknown as Record<string, unknown>;
  if (!proto.hasPointerCapture) proto.hasPointerCapture = () => false;
  if (!proto.releasePointerCapture) proto.releasePointerCapture = () => {};
  if (!proto.scrollIntoView) proto.scrollIntoView = () => {};
  // cmdk(CommandList)挂载时用 ResizeObserver 量列表高度
  if (!window.ResizeObserver) {
    window.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof window.ResizeObserver;
  }
}
