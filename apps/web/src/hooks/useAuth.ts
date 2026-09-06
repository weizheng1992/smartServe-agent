import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import type { UserSession } from './types';

// 登录会话与 JWT 凭证的 localStorage 键名(登录页与 E2E 共用,勿散落硬编码)
export const SESSION_KEY = 'agent_user_session';
export const TOKEN_KEY = 'agent_auth_token';

function clearSession() {
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(TOKEN_KEY);
}

export function useAuth() {
  const navigate = useNavigate();
  const [currentUser, setCurrentUser] = useState<UserSession | null>(null);
  const [isPageHydrated, setIsPageHydrated] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const savedUser = localStorage.getItem(SESSION_KEY);
    const token = localStorage.getItem(TOKEN_KEY);

    // 会话与凭证缺一即视为未登录,清残留后强制重定向 /login
    if (!savedUser || !token) {
      clearSession();
      navigate('/login');
      setIsPageHydrated(true);
      return;
    }

    let parsedUser: UserSession;
    try {
      parsedUser = JSON.parse(savedUser) as UserSession;
      setCurrentUser(parsedUser);
    } catch {
      clearSession();
      navigate('/login');
      setIsPageHydrated(true);
      return;
    }

    // 🛡️ 静默会话校验:GET /api/auth/me(Bearer JWT)。
    // 服务端按 email 回查当前真实记录 —— 物理库重新 seeding 导致的 UUID 漂移在此自愈;
    // 401(凭证无效/已登出/账号不存在)则清除本地会话并强制重新登录。
    (async () => {
      try {
        const res = await fetch('/api/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        const payload = data.data;
        if (res.ok && data.success && payload?.user) {
          if (payload.user.id !== parsedUser.id) {
            console.log(
              `[Session Self-Healing] 🩺 检测到用户 UUID 发生漂移 (原: ${parsedUser.id} ➔ 新: ${payload.user.id})，启动静默自愈校准！`,
            );
            localStorage.setItem(SESSION_KEY, JSON.stringify(payload.user));
            setCurrentUser(payload.user);
          }
        } else {
          clearSession();
          setCurrentUser(null);
          navigate('/login');
        }
      } catch (err) {
        // 网络不可达 ≠ 凭证失效:保留本地会话,由后续业务请求自然暴露错误
        console.warn('[Session Validation] 静默校验网络失败,保留本地会话:', err);
      }
    })();

    setIsPageHydrated(true);
  }, [navigate]);

  const handleLogout = async () => {
    // 服务端吊销(jti 黑名单)尽力而为;本地清除无条件执行
    const token = localStorage.getItem(TOKEN_KEY);
    try {
      if (token) {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
      }
    } catch (err) {
      console.warn('[Auth] 登出请求失败(本地会话仍将清除):', err);
    }
    clearSession();
    setCurrentUser(null);
    navigate('/login');
  };

  return {
    currentUser,
    setCurrentUser,
    isPageHydrated,
    setIsPageHydrated,
    handleLogout,
  };
}
