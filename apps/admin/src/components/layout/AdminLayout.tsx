import React from "react";
import { Outlet } from "react-router";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";

export function AdminLayout() {
  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden font-sans antialiased text-slate-800">
      {/* 左侧侧边栏 */}
      <Sidebar />

      {/* 右侧主体工作区 */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* 顶部 Header */}
        <Header />

        {/* 动态页面内容区 */}
        <main className="flex-1 overflow-y-auto p-6">
          <div className="max-w-7xl mx-auto space-y-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
