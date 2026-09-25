import { setSession } from '@/lib/api';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Button } from 'ui';

// 真实登录(POST /api/auth/login,bcrypt+JWT);0013 起员工经 staff_members
// 凭证登录,JWT 即身份 —— 顶栏切换只对老板开放(服务端换签 token)。
export default function LoginPage({ onLogin }: { onLogin: (email: string) => void }) {
  const [email, setEmail] = useState('test@example.com');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit() {
    setBusy(true);
    setErr('');
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const body = await res.json();
      if (!body.success) throw new Error(body.error || body.message || '登录失败');
      setSession(body.data.token, body.data.user.email);
      onLogin(body.data.user.email);
      navigate('/analytics');
    } catch (e) {
      setErr(String(e).replace('Error: ', ''));
    }
    setBusy(false);
  }

  return (
    <div className="flex h-screen items-center justify-center bg-zinc-100">
      <div className="w-96 rounded-2xl border border-zinc-200 bg-white p-8 shadow-lg">
        <div className="text-lg font-semibold">极光潮品 · 商户后台</div>
        <div className="mt-1 text-[11px] leading-5 text-zinc-400">
          真实登录(bcrypt + JWT)· dev 种子账号:test@example.com(老板)/ ops@aurora(运营)/ wh@aurora(仓储),密码统一
          agent-all-dev
        </div>
        <div className="mt-6 space-y-3">
          <input
            className="w-full rounded-lg border border-zinc-300 px-3 py-2.5 text-sm outline-none focus:border-zinc-900"
            placeholder="邮箱"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            className="w-full rounded-lg border border-zinc-300 px-3 py-2.5 text-sm outline-none focus:border-zinc-900"
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
