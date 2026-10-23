import { FloatingAgent } from '@/components/FloatingAgent';
import { type MenuNode, api, clearSession, currentStaffEmail, errMsgOf, hasBossSession } from '@/lib/api';
import { flattenMenus, routeAllowed } from '@/lib/route-guard';
import AnalyticsPage from '@/pages/analytics';
import BoardPage from '@/pages/board';
import CustomersPage from '@/pages/customers';
import ProductsPage from '@/pages/goods/products';
import SkusPage from '@/pages/goods/skus';
import LiveDeskPage from '@/pages/live-desk';
import LoginPage from '@/pages/login';
import OrderWorkbench from '@/pages/order-manager';
import PromotionsPage from '@/pages/promotions';
import ReportsPage from '@/pages/reports';
import MenusPage from '@/pages/system/menus';
import OwnerMappingsPage from '@/pages/system/owner-mappings';
import RolesPage from '@/pages/system/roles';
import StaffPage from '@/pages/system/staff';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router';
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';

export default function App() {
  const [authed, setAuthed] = useState(() => !!localStorage.getItem('merchant-admin.token'));
  return (
    <BrowserRouter>
      {authed ? (
        <AdminShell
          onLogout={() => {
            clearSession();
            setAuthed(false);
          }}
        />
      ) : (
        <LoginPage onLogin={() => setAuthed(true)} />
      )}
    </BrowserRouter>
  );
}

function AdminShell({ onLogout }: { onLogout: () => void }) {
  const [menus, setMenus] = useState<MenuNode[]>([]);
  // 菜单装载态(2026-10-13 夜评收口:路由守卫的数据基础 —— loading/error 先行
  // 呈现,fail-closed 严禁拿空树放行)
  const [menusState, setMenusState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [role, setRole] = useState('');
  const [staff, setStaff] = useState<Array<{ id: string; email: string; displayName: string; role: string }>>([]);
  const navigate = useNavigate();
  const location = useLocation();

  const refresh = useCallback(async () => {
    setMenusState('loading');
    try {
      const m = await api.menus();
      // transport 归一后业务错误返 body(错误体无 menus 键):如实落 error 态 fail-closed
      if (!Array.isArray(m.menus)) throw new Error(errMsgOf(m, '菜单加载失败'));
      setMenus(m.menus);
      setRole(m.role);
      setStaff((await api.staffList()).staff || []);
      setMenusState('ready');
    } catch (err) {
      console.error('[merchant-admin] 菜单/员工加载失败(网关未启动?)', err);
      setMenusState('error');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const routable = useMemo(() => flattenMenus(menus), [menus]);
  const currentTop = routable.find((r) => location.pathname.startsWith(r.route || '###'))?.top || '';
  // 路由守卫:路径必须落在服务端下发的菜单树内(纪律不变 —— 前端只做可见性,
  // 权限真源在服务端 permCode。信任边界如实(2026-10-15 安全审计 #3):读数据
  // 面的服务端 permCode 闸尚未覆盖,直打网关的数据越权由身份/租户闸兜底、
  // permCode 收敛属待办 —— 本守卫拦截的是页面骨架,不是数据闸)
  const allowed = menusState === 'ready' && routeAllowed(location.pathname, menus);

  // 切换 = 服务端换签目标员工 JWT;始终以保存的老板凭证发起。
  // 业务错误(非老板 403 等)按 transport 语义返 body,errMsgOf 呈现;传输失败仍 throw
  const switchStaff = useCallback(
    (email: string) => {
      api
        .staffSwitch(email)
        .then((b) => {
          if (!b.success) {
            alert(errMsgOf(b, '切换失败'));
            return;
          }
          return refresh();
        })
        .catch((err) => alert(String(err).replace('Error: ', '')));
    },
    [refresh],
  );

  return (
    <div className="flex h-screen bg-zinc-100 text-zinc-900">
      <aside className="w-56 shrink-0 border-r border-zinc-200 bg-white flex flex-col">
        <div className="border-b border-zinc-100 px-4 py-4">
          <div className="text-sm font-semibold">极光潮品 · 商户后台</div>
          <div className="mt-0.5 text-[11px] text-zinc-400">apps/merchant-admin</div>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 pb-4">
          {menus.map((dir) => (
            <div key={dir.id} className="mb-2">
              {dir.menuType === 'directory' && (
                <>
                  <div className="mt-3 px-2 text-[11px] tracking-wider text-zinc-400">{dir.name}</div>
                  {(dir.children || [])
                    .filter((c) => c.menuType === 'menu')
                    .map((m) => (
                      <Button
                        type="button"
                        key={m.id}
                        variant="ghost"
                        onClick={() => m.route && navigate(m.route)}
                        className={`block w-full cursor-pointer justify-start rounded-lg px-3 py-1.5 text-left text-[13px] font-normal ${
                          location.pathname.startsWith(m.route || '###')
                            ? 'bg-zinc-900 text-white hover:bg-zinc-900 hover:text-white'
                            : 'text-zinc-600 hover:bg-zinc-50 hover:text-zinc-600'
                        }`}
                      >
                        {m.name}
                      </Button>
                    ))}
                </>
              )}
            </div>
          ))}
        </nav>
      </aside>

      <main className="relative flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-200 bg-white px-6">
          <div className="text-sm font-medium text-zinc-600">{currentTop}</div>
          <div className="flex items-center gap-3 text-xs">
            {hasBossSession() && (
              <Select value={currentStaffEmail()} onValueChange={(v) => void switchStaff(v)}>
                <SelectTrigger
                  aria-label="身份切换"
                  className="h-auto w-fit rounded-full bg-zinc-900 px-3 py-1.5 text-xs text-white border-zinc-900"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {staff.map((s) => (
                    <SelectItem key={s.id} value={s.email}>
                      {s.displayName} · {s.role}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <span className="text-zinc-400">
              {currentStaffEmail()} · {role}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-auto px-1 py-0.5 text-[11px] font-normal text-zinc-400 hover:text-zinc-900"
              onClick={onLogout}
            >
              退出
            </Button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          {menusState === 'loading' ? (
            <div className="flex h-full items-center justify-center text-xs text-zinc-400">菜单加载中…</div>
          ) : menusState === 'error' ? (
            <div className="flex h-full flex-col items-center justify-center gap-3">
              <div className="text-sm text-zinc-500">菜单加载失败(网关未启动或会话失效)</div>
              <Button type="button" variant="outline" className="rounded-lg text-xs" onClick={() => void refresh()}>
                重试
              </Button>
            </div>
          ) : location.pathname === '/login' ? (
            // 已登录直敲 /login:回工作台,不落「无权访问」卡(/login 不在菜单树,
            // 守卫必然拦截;登录面只属于未登录整树分支)
            <Navigate replace to="/analytics" />
          ) : !allowed ? (
            <div className="flex h-full flex-col items-center justify-center gap-2">
              <div className="text-3xl">🔒</div>
              <div className="text-sm font-semibold text-zinc-800">无权访问</div>
              <div className="max-w-sm text-center text-xs text-zinc-500">
                当前身份的菜单中没有此页面(直敲 URL 已被拦截)。如需开通请联系管理员调整角色菜单。
              </div>
            </div>
          ) : (
            <Routes>
              <Route path="/analytics" element={<AnalyticsPage role={role} />} />
              <Route path="/board" element={<BoardPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/orders" element={<OrderWorkbench scope="orders" />} />
              <Route path="/approvals" element={<OrderWorkbench scope="approvals" />} />
              {/* 旧 /live-desk 并存作回退面(2026-10-24 收敛:退出菜单,菜单指向
                  /approvals 待办审核 + /agent-desk 客服工作台;e2e 回绿钉仍走本路由) */}
              <Route path="/live-desk" element={<OrderWorkbench scope="live-desk" />} />
              {/* 坐席台独立页(P2);2026-10-24 菜单名升正「客服工作台」 */}
              <Route path="/agent-desk" element={<LiveDeskPage />} />
              <Route path="/promotions" element={<PromotionsPage />} />
              <Route path="/customers" element={<CustomersPage />} />
              <Route path="/menus" element={<MenusPage />} />
              <Route path="/roles" element={<RolesPage />} />
              <Route path="/staff" element={<StaffPage />} />
              <Route path="/owner-mappings" element={<OwnerMappingsPage />} />
              <Route path="/products" element={<ProductsPage />} />
              <Route path="/products/:code" element={<ProductsPage focusCode="*" />} />
              <Route path="/skus" element={<SkusPage />} />
              <Route path="/spi-logs" element={<OrderWorkbench scope="spi-logs" />} />
              <Route path="*" element={<NotFoundRedirect />} />
            </Routes>
          )}
        </div>

        <FloatingAgent route={location.pathname} />
      </main>
    </div>
  );
}

function NotFoundRedirect() {
  const navigate = useNavigate();
  useEffect(() => {
    navigate('/products', { replace: true });
  }, [navigate]);
  return null;
}
