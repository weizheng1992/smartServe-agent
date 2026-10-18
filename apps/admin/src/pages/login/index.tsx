import { authApi, setSession } from '../../lib/api';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Button, Input } from 'ui';

// 平台运营者登录(2026-10-18 平台面零鉴权收口):员工 JWT(role='platform_admin')
// 即管控台身份。dev 种子账号 platform@aurora(启动期幂等种子),密码统一 agent-all-dev。
export default function LoginPage() {
  const [email, setEmail] = useState('platform@aurora');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit() {
    setBusy(true);
    setErr('');
    try {
      const body = await authApi.login(email, password);
      if (!body.success || !body.data) throw new Error(body.error || body.message || '登录失败');
      const data = body.data as { token: string; user: { email: string } };
      setSession(data.token, data.user.email);
      navigate('/dashboard');
    } catch (e) {
      setErr(String(e).replace('Error: ', ''));
    }
    setBusy(false);
  }

  return (
    <div className="flex h-screen items-center justify-center bg-zinc-100">
      <div className="w-96 rounded-2xl border border-zinc-200 bg-white p-8 shadow-lg">
        <div className="text-lg font-semibold">极光潮品 · SaaS 管控台</div>
        <div className="mt-1 text-[11px] leading-5 text-zinc-400">
          平台运营者登录(员工 JWT,role=platform_admin)· dev 种子账号:platform@aurora,密码统一 agent-all-dev
        </div>
        <div className="mt-6 space-y-3">
          <Input
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2.5 text-sm shadow-none focus-visible:border-zinc-900 focus-visible:ring-0"
            placeholder="邮箱"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2.5 text-sm shadow-none focus-visible:border-zinc-900 focus-visible:ring-0"
            type="password"
            placeholder="密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void submit()}
          />
          {err && <div className="text-xs text-rose-600">{err}</div>}
          <Button className="w-full" disabled={busy || !password} onClick={() => void submit()}>
            {busy ? '登录中…' : '登录'}
          </Button>
        </div>
      </div>
    </div>
  );
}
