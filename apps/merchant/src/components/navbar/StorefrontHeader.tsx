import React, { useState } from 'react';
import { Link } from 'react-router';
import { useLocation } from 'react-router';
import { useCurrentUser } from '../../context/UserContext';

export function StorefrontHeader({
  cartCount = 0,
  ordersCount = 0,
  addressCount = 0,
}: {
  cartCount?: number;
  ordersCount?: number;
  addressCount?: number;
}) {
  const { pathname } = useLocation();
  const { user, switchUser, presetUsers, loginUser } = useCurrentUser();
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [customName, setCustomName] = useState('');
  const [isCustomLoginOpen, setIsCustomLoginOpen] = useState(false);
  const [syncedCartCount, setSyncedCartCount] = useState(cartCount);

  React.useEffect(() => {
    setSyncedCartCount(cartCount);
  }, [cartCount]);

  React.useEffect(() => {
    const updateCount = () => {
      try {
        const stored = JSON.parse(localStorage.getItem('aurora_store_cart') || '[]');
        const total = stored.reduce((sum: number, it: any) => sum + (it.quantity || 1), 0);
        setSyncedCartCount(total);
      } catch {
        // ignore
      }
    };
    updateCount();
    window.addEventListener('cart_updated', updateCount);
    window.addEventListener('storage', updateCount);
    return () => {
      window.removeEventListener('cart_updated', updateCount);
      window.removeEventListener('storage', updateCount);
    };
  }, []);

  const navLinks = [
    { label: '🏬 选购首页', href: '/' },
    { label: '🛒 购物车', href: '/cart', count: syncedCartCount },
    { label: '📋 我的订单', href: '/orders', count: ordersCount },
    { label: '📍 地址簿', href: '/addresses', count: addressCount },
  ];

  const handleCustomLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customName.trim()) return;
    loginUser({
      name: customName.trim(),
      tier: '注册会员',
    });
    setCustomName('');
    setIsCustomLoginOpen(false);
    setIsUserMenuOpen(false);
  };

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-xs">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <Link to="/" className="flex items-center space-x-3 hover:opacity-90 transition">
          <div className="w-10 h-10 rounded-lg bg-emerald-600 flex items-center justify-center text-white font-bold text-xl shadow-xs">
            A
          </div>
          <div>
            <div className="font-bold text-lg text-slate-900 tracking-tight flex items-center space-x-2">
              <span>极光潮品 AURORA LUXE</span>
              <span className="text-xs bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded font-medium">
                独立自研商城
              </span>
            </div>
            <div className="text-xs text-slate-500 hidden sm:block">
              独立数据库物理隔离 · SPU / SKU 多规格电商体系 (Port 3005)
            </div>
          </div>
        </Link>

        {/* 顶部导航菜单与用户操作区 */}
        <div className="flex items-center space-x-2 sm:space-x-3">
          {/* 当前登录用户切换入口 */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
              className="flex items-center space-x-2 text-xs bg-slate-50 hover:bg-slate-100 border border-slate-200 px-3 py-1.5 rounded-full cursor-pointer transition shadow-2xs"
            >
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-slate-500 hidden md:inline">当前用户:</span>
              <strong className="text-slate-900 font-bold">{user.name}</strong>
              <span className="text-[10px] bg-emerald-100 text-emerald-800 font-bold px-1.5 py-0.2 rounded">
                {user.tier}
              </span>
              <span className="text-slate-400 text-[10px]">▼</span>
            </button>

            {/* 用户下拉菜单 */}
            {isUserMenuOpen && (
              <div className="absolute right-0 mt-2 w-72 bg-white rounded-2xl shadow-xl border border-slate-200 p-3 z-50 text-xs space-y-3">
                <div className="border-b border-slate-100 pb-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold text-slate-400">当前账户档案</span>
                    <span className="font-mono text-[10px] text-slate-400 bg-slate-50 px-1.5 py-0.5 rounded border border-slate-100">
                      {user.id}
                    </span>
                  </div>
                  <div className="flex items-center space-x-2.5 mt-2">
                    <div className="w-8 h-8 rounded-full bg-emerald-600 text-white flex items-center justify-center font-bold text-sm">
                      {user.name.slice(0, 1)}
                    </div>
                    <div>
                      <div className="font-bold text-slate-900">{user.name}</div>
                      <div className="text-[11px] text-slate-500 font-mono">
                        {user.phone} · {user.tier}
                      </div>
                    </div>
                  </div>
                  <div className="text-[11px] text-slate-400 mt-1.5 truncate">📍 {user.defaultAddress}</div>
                </div>

                {/* 快捷切换预置演示账号 */}
                <div className="space-y-1.5">
                  <div className="text-[11px] font-bold text-slate-500">👥 快捷切换演示账号:</div>
                  <div className="space-y-1">
                    {presetUsers.map((preset) => (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => {
                          switchUser(preset);
                          setIsUserMenuOpen(false);
                        }}
                        className={`w-full text-left p-2 rounded-xl border flex items-center justify-between transition cursor-pointer ${
                          user.id === preset.id
                            ? 'bg-emerald-50 border-emerald-300 text-emerald-950 font-semibold'
                            : 'bg-slate-50 hover:bg-slate-100 border-slate-100 text-slate-700'
                        }`}
                      >
                        <div className="flex items-center space-x-2">
                          <span className="font-bold">{preset.name}</span>
                          <span className="text-[10px] text-slate-400 font-mono">({preset.id})</span>
                        </div>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-white border border-slate-200">
                          {preset.tier}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* 自定义登录 */}
                <div className="pt-2 border-t border-slate-100">
                  {isCustomLoginOpen ? (
                    <form onSubmit={handleCustomLogin} className="space-y-2">
                      <input
                        type="text"
                        value={customName}
                        onChange={(e) => setCustomName(e.target.value)}
                        placeholder="输入自定义用户名"
                        className="w-full text-xs px-2.5 py-1.5 rounded-lg border border-slate-300 focus:outline-emerald-500"
                        // biome-ignore lint/a11y/noAutofocus: 搜索弹层打开即聚焦,刻意 UX
                        autoFocus
                      />
                      <div className="flex justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => setIsCustomLoginOpen(false)}
                          className="px-2 py-1 rounded text-[11px] text-slate-500 hover:bg-slate-100 cursor-pointer"
                        >
                          取消
                        </button>
                        <button
                          type="submit"
                          className="px-2.5 py-1 rounded text-[11px] bg-emerald-600 text-white font-bold hover:bg-emerald-500 cursor-pointer"
                        >
                          登录
                        </button>
                      </div>
                    </form>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setIsCustomLoginOpen(true)}
                      className="w-full text-center py-1.5 text-xs text-emerald-700 hover:bg-emerald-50 rounded-lg font-medium cursor-pointer transition"
                    >
                      ➕ 登录其他自定义账号
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>

          {navLinks.map((item) => {
            const isActive = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                to={item.href}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition shadow-2xs flex items-center space-x-1.5 ${
                  isActive
                    ? 'bg-emerald-600 text-white font-semibold shadow-xs'
                    : 'text-slate-700 bg-white border border-slate-300 hover:bg-slate-50'
                }`}
              >
                <span>{item.label}</span>
                {item.count !== undefined && item.count > 0 && (
                  <span
                    className={`text-[11px] px-1.5 py-0.2 rounded-full font-bold ${
                      isActive ? 'bg-white text-emerald-700' : 'bg-emerald-600 text-white'
                    }`}
                  >
                    {item.count}
                  </span>
                )}
              </Link>
            );
          })}

          {/* 管理后台跳转 */}
          <a
            href="/admin"
            className="px-3 py-1.5 text-xs font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 transition hidden sm:inline-flex items-center space-x-1"
          >
            <span>⚙️ 商户后台</span>
          </a>
        </div>
      </div>
    </header>
  );
}
