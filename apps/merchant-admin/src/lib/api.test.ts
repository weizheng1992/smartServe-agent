import '@testing-library/jest-dom/vitest';
import { beforeEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { api, authHeaders, clearSession, hasBossSession, setSession } from '@/lib/api';
import { gatewayUp, installLiveFetch, login } from '@/test/live-api';

// 集成测试(真实网关 + 真实库;不 mock 数据)。authHeaders/会话存取为纯
// localStorage 逻辑,不依赖网络;其余走真实登录与真实业务端点。
const d = gatewayUp ? describe : describe.skip;

beforeAll(() => {
  installLiveFetch(); // 仅补全相对路径基址,不伪造响应
});

beforeEach(() => {
  localStorage.clear();
  installLiveFetch();
});

describe('会话凭证(纯逻辑)', () => {
  it('无 token 时 authHeaders 不带 Authorization', () => {
    expect(authHeaders().Authorization).toBeUndefined();
    expect(authHeaders()['x-tenant-id']).toBe('aurora');
  });

  it('setSession 后带 Bearer;clearSession 清空全部键', () => {
    setSession('tok-1', 'boss@aurora');
    expect(authHeaders().Authorization).toBe('Bearer tok-1');
    clearSession();
    expect(authHeaders().Authorization).toBeUndefined();
    expect(hasBossSession()).toBe(false);
  });
});

d('身份链路(真实登录/真实端点)', () => {
  it('boss 登录 → 切换到仓储 → 再切回老板(原始凭证留存)', async () => {
    const boss = await login('test@example.com');
    setSession(boss.token, boss.email);

    const out = await api.staffSwitch('wh@aurora');
    expect(out.role).toBe('warehouse_operator');
    // 当前会话已切到目标员工 token
    const whToken = localStorage.getItem('merchant-admin.token')!;
    expect(authHeaders().Authorization).toBe(`Bearer ${whToken}`);
    expect(localStorage.getItem('merchant-admin.staff')).toBe('wh@aurora');
    // 老板凭证留存,可切回
    const bossBlob = JSON.parse(localStorage.getItem('merchant-admin.boss')!);
    expect(bossBlob.email).toBe('test@example.com');

    // 切回老板:服务端以留存凭证换签,身份恢复
    const back = await api.staffSwitch('test@example.com');
    expect(back.role).toBe('finance_owner');
    expect(localStorage.getItem('merchant-admin.staff')).toBe('test@example.com');
    expect(hasBossSession()).toBe(true);
  });

  it('非老板不能分配角色权限(业务 403 返回 body,不抛错)', async () => {
    const ops = await login('ops@aurora');
    setSession(ops.token, ops.email);
    const body = await api.roles.saveMenus('sales_viewer', []);
    expect(body.success).toBe(false);
    expect(String(body.message)).toContain('仅老板');
    // 未产生任何写副作用
    expect(hasBossSession()).toBe(false);
  });

  it('未知员工登录被拒(诚实 401)', async () => {
    await expect(login('nobody@aurora', 'wrong-password')).rejects.toThrow('登录失败');
  });
});
