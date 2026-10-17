// 商户内嵌运营台(2026-10-17 审查裁决删除):c7b26cd(2026-09-27)给 /api/admin/*
// 族上了员工身份闸(_require_staff)后,本内嵌台无身份源,全部业务面(订单/
// 审批/客服台/SPU/SKU/SPI)永久 401 不可达 —— 1966 行死代码整页删除,仅保留
// 员工鉴权引导卡。契约钉于 e2e/merchantConsoleAudit.e2e.ts:「/admin 只出引导
// 卡,不渲染业务数据与 Tab」+「管理族 API 匿名必 401」。
// 管理面归宿 = 独立商户后台 apps/merchant-admin(3006,员工登录面);审批族
// UI 审计的迁移宿主与历史实弹证据见该 e2e 文件头注。商品价格/库存编辑
// (open-merchant-integration spec Story 9)同样移交该后台,见
// .scratch/open-merchant-integration/issues/07-story9-handover.md。
export default function MerchantAdminPage() {
  return (
    <div className="min-h-screen bg-slate-100 flex items-center justify-center font-sans p-6">
      <div className="bg-white rounded-lg shadow-md border border-slate-200 max-w-md p-8 text-center">
        <div className="w-12 h-12 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center text-2xl font-bold mx-auto mb-4">
          !
        </div>
        <h1 className="text-lg font-semibold text-slate-900 mb-2">商户管理面已启用员工鉴权</h1>
        <p className="text-sm text-slate-600 leading-6">
          订单 / 审批 / 会话等管理接口现要求商户员工登录(Bearer JWT)。本内嵌工作台尚未接入员工登录, 请使用独立商户后台(
          <code className="bg-slate-100 rounded px-1">bun run dev:merchant-admin</code>
          ,端口 3006)完成同类操作。
        </p>
      </div>
    </div>
  );
}
