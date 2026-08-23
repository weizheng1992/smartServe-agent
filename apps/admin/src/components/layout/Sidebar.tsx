import React from "react";
import { Link, useLocation } from "react-router";

interface NavItem {
  name: string;
  path: string;
  badge?: string;
  icon: (props: { className?: string }) => React.ReactElement;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    title: "业务运营 (Operations)",
    items: [
      {
        name: "商户租户管理",
        path: "/tenants",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
            />
          </svg>
        ),
      },
      {
        name: "全景会话回放",
        path: "/conversations",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
        ),
      },
      {
        name: "审批与风控审计",
        path: "/audits",
        badge: "HITL",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
            />
          </svg>
        ),
      },
      {
        name: "人物画像事实素描",
        path: "/personas",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
            />
          </svg>
        ),
      },
    ],
  },
  {
    title: "智能体与知识 (Agent & RAG)",
    items: [
      {
        name: "知识库与检索演练",
        path: "/rag-studio",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
            />
          </svg>
        ),
      },
      {
        name: "技能与 MCP 工具市场",
        path: "/skills-tools",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z"
            />
          </svg>
        ),
      },
      {
        name: "评测与 Prompt 实验",
        path: "/evals",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
            />
          </svg>
        ),
      },
    ],
  },
  {
    title: "平台与治理 (Platform)",
    items: [
      {
        name: "计量计费与配额",
        path: "/billing",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        ),
      },
      {
        name: "安全合规与围栏",
        path: "/guardrails",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
            />
          </svg>
        ),
      },
      {
        name: "系统与 LLM 日志",
        path: "/system-logs",
        icon: ({ className = "w-4 h-4" }) => (
          <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 6h16M4 10h16M4 14h16M4 18h16"
            />
          </svg>
        ),
      },
    ],
  },
];

export function Sidebar() {
  const location = useLocation();

  return (
    <aside className="w-64 bg-white border-r border-slate-200 flex flex-col shrink-0 h-screen sticky top-0">
      {/* 品牌标识 */}
      <div className="h-14 px-5 border-b border-slate-200 flex items-center gap-2.5">
        <div className="w-7 h-7 bg-slate-900 rounded-lg flex items-center justify-center text-white font-bold text-xs tracking-wider shadow-xs">
          CP
        </div>
        <div>
          <h1 className="text-sm font-semibold text-slate-900 leading-tight">
            Agent Control Plane
          </h1>
          <p className="text-[10px] text-slate-400 font-medium">
            SaaS 多租户管理中台
          </p>
        </div>
      </div>

      {/* 导航菜单 */}
      <div className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
        {NAV_GROUPS.map((group) => (
          <div key={group.title}>
            <div className="px-2 mb-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              {group.title}
            </div>
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const isActive =
                  item.path === "/"
                    ? location.pathname === "/"
                    : location.pathname.startsWith(item.path);

                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={`flex items-center justify-between px-2.5 py-2 rounded-lg text-xs font-medium transition-colors ${
                      isActive
                        ? "bg-slate-100 text-slate-900 font-semibold"
                        : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <item.icon
                        className={`w-4 h-4 ${isActive ? "text-slate-900" : "text-slate-400"}`}
                      />
                      <span>{item.name}</span>
                    </div>
                    {item.badge && (
                      <span className="px-1.5 py-0.5 text-[10px] font-semibold bg-rose-50 text-rose-600 border border-rose-200 rounded-md">
                        {item.badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 底部系统状态 */}
      <div className="p-3.5 border-t border-slate-200 bg-slate-50/50 flex items-center justify-between text-xs text-slate-500">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-[11px] font-medium text-slate-600">
            Engine v2.4 运行中
          </span>
        </div>
        <span className="text-[10px] text-slate-400 font-mono">
          10 Nodes Active
        </span>
      </div>
    </aside>
  );
}
