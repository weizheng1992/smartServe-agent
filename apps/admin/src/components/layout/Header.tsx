import React from "react";
import { useLocation } from "react-router";
import {
  useAdminTenantStore,
  SUPPORTED_TENANTS,
} from "../../store/tenantStore";

const PAGE_TITLE_MAP: Record<string, { title: string; subtitle: string }> = {
  "/tenants": {
    title: "商户租户管理",
    subtitle: "平台入驻商户、API Key 与 SPI Webhook 配置",
  },
  "/conversations": {
    title: "全景会话回放",
    subtitle: "多租户会话全景、状态机流转与 LangGraph 决策透视",
  },
  "/audits": {
    title: "审批与风控审计",
    subtitle: "HITL 审批记录、风控策略拦截与决议留存",
  },
  "/personas": {
    title: "人物画像事实素描",
    subtitle: "多租户长程事实记忆 (Persona Facts) 检索与修正",
  },
  "/rag-studio": {
    title: "知识库与检索演练",
    subtitle: "RAG 知识切片管理、向量相似度演练与召回测试",
  },
  "/skills-tools": {
    title: "技能与 MCP 工具市场",
    subtitle: "OpenAPI 动态工具、原生工具与 MCP Server 注册列表",
  },
  "/evals": {
    title: "评测与 Prompt 实验",
    subtitle: "Agent 准确率、忠实度评测指标与实验版本对比",
  },
  "/billing": {
    title: "计量计费与配额",
    subtitle: "Token 消耗、费用估算统计与商户配额治理",
  },
  "/guardrails": {
    title: "安全合规与围栏",
    subtitle: "敏感词黑名单、SQL 防注入规则与输出拦截策略",
  },
  "/system-logs": {
    title: "系统与 LLM 日志",
    subtitle: "全链路 LLM 耗时/Token、意图日志与异常追踪",
  },
};

export function Header() {
  const location = useLocation();
  const { selectedTenantId, setSelectedTenantId, getSelectedTenant } =
    useAdminTenantStore();
  const activeTenant = getSelectedTenant();

  const currentPath =
    Object.keys(PAGE_TITLE_MAP).find((p) => location.pathname.startsWith(p)) ||
    "/tenants";

  const pageInfo = PAGE_TITLE_MAP[currentPath] || {
    title: "控制台大盘",
    subtitle: "企业级多租户 SaaS Agent 控制平面",
  };

  return (
    <header className="h-14 bg-white border-b border-slate-200 px-6 flex items-center justify-between sticky top-0 z-20">
      {/* 左侧面包屑与标题 */}
      <div className="flex items-center gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-slate-900">
              {pageInfo.title}
            </h2>
            <span className="text-slate-300">/</span>
            <span className="text-xs text-slate-500 font-medium">
              {pageInfo.subtitle}
            </span>
          </div>
        </div>
      </div>

      {/* 右侧全局租户切换器与操作 */}
      <div className="flex items-center gap-3">
        {/* 全局租户穿透选择器 */}
        <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-lg">
          <span className="text-[11px] font-medium text-slate-500">
            全局租户穿透:
          </span>
          <select
            value={selectedTenantId}
            onChange={(e) => setSelectedTenantId(e.target.value)}
            className="text-xs font-semibold text-slate-800 bg-transparent focus:outline-hidden cursor-pointer"
          >
            {SUPPORTED_TENANTS.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded-md font-mono border ${
              activeTenant.badgeColor ||
              "bg-slate-100 text-slate-600 border-slate-300"
            }`}
          >
            {activeTenant.id}
          </span>
        </div>

        {/* 平台管理员身份 */}
        <div className="flex items-center gap-2 pl-3 border-l border-slate-200">
          <div className="w-7 h-7 rounded-full bg-slate-800 text-white flex items-center justify-center text-xs font-semibold">
            AD
          </div>
          <div className="hidden sm:block text-left">
            <div className="text-xs font-semibold text-slate-800">
              Admin Platform
            </div>
            <div className="text-[10px] text-slate-400">Super Admin</div>
          </div>
        </div>
      </div>
    </header>
  );
}
