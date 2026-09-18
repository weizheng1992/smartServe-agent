import { useCallback, useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Route, Routes, useLocation, useNavigate } from 'react-router';
import { Button } from 'ui';
import { api, currentStaff, switchStaff, type MenuNode } from '@/lib/api';
import AnalyticsPage from '@/pages/analytics';
import OrderWorkbench from '@/pages/order-manager';
import ProductsPage from '@/pages/goods/products';
import LoginPage from '@/pages/login';
import PromotionsPage from '@/pages/promotions';
import CustomersPage from '@/pages/customers';
import MenusPage from '@/pages/system/menus';
import RolesPage from '@/pages/system/roles';
import StaffPage from '@/pages/system/staff';
import ReportsPage from '@/pages/reports';
import { FloatingAgent } from '@/components/FloatingAgent';

function flattenMenus(nodes: MenuNode[]): Array<MenuNode & { top: string }> {
  return nodes.flatMap((n) => [
    ...(n.menuType === 'menu' ? [{ ...n, top: n.name }] : []),
    ...flattenMenus(n.children || []),
  ]);
}

export default function App() {
  const [authed, setAuthed] = useState(() => !!localStorage.getItem('merchant-admin.token'));
  return (
    <BrowserRouter>
      {authed ? <AdminShell onLogout={() => { localStorage.removeItem('merchant-admin.token'); setAuthed(false); }} /> : <LoginPage onLogin={() => setAuthed(true)} />}
    </BrowserRouter>
  );
}

function AdminShell({ onLogout }: { onLogout: () => void }) {
  const [menus, setMenus] = useState<MenuNode[]>([]);
  const [role, setRole] = useState('');
  const [staff, setStaff] = useState<Array<{ id: string; email: string; displayName: string; role: string }>>([]);
  const navigate = useNavigate();
  const location = useLocation();

  const refresh = useCallback(async () => {
    try {
      const m = await api.menus();
      setMenus(m.menus);
      setRole(m.role);
      setStaff((await api.staffList()).staff);
    } catch (err) {
      console.error('[merchant-admin] 菜单/员工加载失败(网关未启动?)', err);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const routable = useMemo(() => flattenMenus(menus), [menus]);
  const currentTop = routable.find((r) => location.pathname.startsWith(r.route || '###'))?.top || '';

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
                      <span
                        key={m.id}
                        onClick={() => m.route && navigate(m.route)}
                        className={`block cursor-pointer rounded-lg px-3 py-1.5 text-[13px] ${
                          location.pathname.startsWith(m.route || '###')
                            ? 'bg-zinc-900 text-white'
                            : 'text-zinc-600 hover:bg-zinc-50'
                        }`}
                      >
                        {m.name}
                      </span>
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
            <select
              className="rounded-full bg-zinc-900 px-3 py-1.5 text-white"
              value={currentStaff()}
              onChange={(e) => {
                switchStaff(e.target.value);
                void refresh();
              }}
            >
              {staff.map((s) => (
                <option key={s.id} value={s.email}>
                  {s.displayName} · {s.role}
                </option>
              ))}
            </select>
            <span className="text-zinc-400">{currentStaff()}</span>
            <button className="text-[11px] text-zinc-400 hover:text-zinc-900" onClick={onLogout}>退出</button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          <Routes>
            <Route path="/analytics" element={<AnalyticsPage role={role} />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/orders" element={<OrderWorkbench initialTab="orders" />} />
            <Route path="/approvals" element={<OrderWorkbench initialTab="approvals" />} />
            <Route path="/live-desk" element={<OrderWorkbench initialTab="live_desk" />} />
            <Route path="/promotions" element={<PromotionsPage />} />
            <Route path="/customers" element={<CustomersPage />} />
            <Route path="/menus" element={<MenusPage />} />
            <Route path="/roles" element={<RolesPage />} />
            <Route path="/staff" element={<StaffPage />} />
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/skus" element={<ProductsPage />} />
            <Route path="/spi-logs" element={<OrderWorkbench initialTab="spi_logs" />} />
          </Routes>
        </div>

        <FloatingAgent route={location.pathname} />
      </main>
    </div>
  );
}
