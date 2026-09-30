/**
 * @vitest-environment node
 * (jsdom 环境下 import vite.config 会连带 esbuild,其 TextEncoder 不变量在 jsdom 全局下炸;
 * 本测试无 DOM 依赖,node 环境即可)
 * 客户端路由不得被 Vite 代理前缀截胡(实弹 2026-09-30 merchant-admin:代理键 '/spi'
 * 吃掉客户端路由 '/spi-logs',刷新即 GET /spi-logs 被代理到网关吃 404,SPA 回退永不
 * 生效 —— 两应用同批收口 '/spi/' 后,本契约钉住 merchant 侧不再回退;'/api' 仍是
 * 裸前缀键,未来任何 '/api-xxx' 客户端路由都会在此红)。
 * 契约:App.tsx 注册的每个客户端路由,都不得以任一字符串型 proxy 键为前缀。
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import viteConfig from '../vite.config';

const here = dirname(fileURLToPath(import.meta.url));

function clientRoutes(): string[] {
  const appTsx = readFileSync(resolve(here, 'App.tsx'), 'utf8');
  return [...appTsx.matchAll(/path="([^"]+)"/g)].map((m) => m[1]);
}

describe('vite 代理键与客户端路由碰撞', () => {
  it('任一客户端路由都不得被字符串型代理前缀截胡', () => {
    // '^' 开头是正则键,不走 startsWith 前缀语义,不在本契约内
    const proxyKeys = Object.keys(viteConfig.server?.proxy ?? {}).filter((k) => !k.startsWith('^'));
    const routes = clientRoutes();
    expect(routes.length).toBeGreaterThan(5);
    expect(proxyKeys.length).toBeGreaterThan(0);
    for (const route of routes) {
      for (const key of proxyKeys) {
        expect(route.startsWith(key), `客户端路由 ${route} 被代理键 ${key} 截胡(刷新即打到网关)`).toBe(false);
      }
    }
  });
});
