import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup, configure } from '@testing-library/react';

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
