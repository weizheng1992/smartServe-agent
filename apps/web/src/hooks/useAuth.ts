import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import type { UserSession } from "./types";

export function useAuth() {
  const navigate = useNavigate();
  const [currentUser, setCurrentUser] = useState<UserSession | null>(null);
  const [isPageHydrated, setIsPageHydrated] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedUser = localStorage.getItem("agent_user_session");
      if (savedUser) {
        try {
          const parsedUser = JSON.parse(savedUser);
          setCurrentUser(parsedUser);

          // 🛡️ [会话自愈对齐防御锁]:
          // 异步静默调用后端 /api/auth/login 校验当前 email 在物理库中的最新 UUID。
          // 防止由于物理库重新 seeding 导致本地浏览器 localStorage 残留老 UUID（如 u_default_id）而产生多租户数据脱节与查单失败！
          (async () => {
            try {
              const checkRes = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: parsedUser.email }),
              });
              const checkData = await checkRes.json();
              if (
                checkData.success &&
                checkData.user &&
                checkData.user.id !== parsedUser.id
              ) {
                console.log(
                  `[Session Self-Healing] 🩺 检测到用户 UUID 发生漂移 (原: ${parsedUser.id} ➔ 新: ${checkData.user.id})，启动静默自愈校准！`,
                );
                localStorage.setItem(
                  "agent_user_session",
                  JSON.stringify(checkData.user),
                );
                setCurrentUser(checkData.user);
              }
            } catch (err) {
              console.warn(
                "[Session Self-Healing] Silent validation failed:",
                err,
              );
            }
          })();
        } catch (e) {
          localStorage.removeItem("agent_user_session");
          navigate("/login");
        }
      } else {
        // 未登录则强制重定向跳转至 /login 物理路由页面！
        navigate("/login");
      }
      setIsPageHydrated(true);
    }
  }, [navigate]);

  const handleLogout = () => {
    localStorage.removeItem("agent_user_session");
    setCurrentUser(null);
    navigate("/login");
  };

  return {
    currentUser,
    setCurrentUser,
    isPageHydrated,
    setIsPageHydrated,
    handleLogout,
  };
}
