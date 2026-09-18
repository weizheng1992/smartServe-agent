import React from "react";
import {
  ApprovalContextDrawer,
  ApprovalRiskBadge,
  Badge,
  Button,
  CheckCircle2,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  RichCardRenderer,
  ShieldAlert,
  Textarea,
} from "ui";
import { useWorkbench } from "../workbench";

export function SpiLogsTab() {
  const {
    activeTab,
    filteredAuditLogs, setSelectedLog, setSpiSearchQuery, spiSearchQuery,
  } = useWorkbench();
  if (activeTab !== 'spi_logs') return null;
  return (
    <>
          <div className="space-y-6">
            <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs space-y-4">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <h3 className="text-sm font-bold text-slate-900">🔌 商户 SPI 开放接入参数 (Aurora SPI Specs)</h3>
                <span className="text-xs bg-emerald-100 text-emerald-800 px-2.5 py-0.5 rounded font-medium">
                  在线就绪 (Ready)
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <div className="text-slate-500 font-medium">SPI 基础服务 URL (spiBaseUrl)</div>
                  <div className="font-mono text-slate-900 font-bold mt-1">http://localhost:3005</div>
                </div>

                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <div className="text-slate-500 font-medium">API 签名密钥 (HMAC-SHA256 Secret)</div>
                  <div className="font-mono text-slate-900 font-bold mt-1">aurora_secret_key_8899</div>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden space-y-0">
              <div className="p-4 border-b border-slate-100 bg-slate-50 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <span className="text-xs font-bold text-slate-900">
                    📥 来自 Agent 平台的实时 SPI 调度审计流水 (merchant_audit_logs)
                  </span>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    物理落盘于商户独立数据库，自动记录幂等防重 Token 与签名
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <Input
                    type="text"
                    placeholder="搜索流水 ID / 订单号 / 动作..."
                    value={spiSearchQuery}
                    onChange={(e) => setSpiSearchQuery(e.target.value)}
                    className="text-xs h-8 w-64 bg-white"
                  />
                </div>
              </div>

              {filteredAuditLogs.length === 0 ? (
                <div className="p-12 text-center text-slate-400 text-xs">
                  暂无匹配的 SPI 变更记录。可在前台拉起 AI 客服发起改地址或退款进行测试。
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase font-semibold">
                      <tr>
                        <th className="p-3.5">流水 ID</th>
                        <th className="p-3.5">对应订单号</th>
                        <th className="p-3.5">动作类型</th>
                        <th className="p-3.5">幂等防重 Key</th>
                        <th className="p-3.5">执行时间</th>
                        <th className="p-3.5 text-right">报文详情</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-slate-700">
                      {filteredAuditLogs.map((log) => (
                        <tr key={log.id} className="hover:bg-slate-50/80 transition">
                          <td className="p-3.5 font-mono text-slate-900">{log.id.slice(0, 8)}...</td>
                          <td className="p-3.5 font-semibold text-slate-800">{log.order_id}</td>
                          <td className="p-3.5">
                            <Badge variant="outline" className="bg-blue-100 text-blue-800 border-blue-200 font-bold">
                              {log.action_type}
                            </Badge>
                          </td>
                          <td className="p-3.5 font-mono text-[11px] text-slate-500">
                            {log.idempotency_key?.slice(0, 16)}...
                          </td>
                          <td className="p-3.5 text-slate-500">{new Date(log.created_at).toLocaleTimeString()}</td>
                          <td className="p-3.5 text-right">
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              onClick={() => setSelectedLog(log)}
                              className="text-xs h-7 px-2.5 font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 cursor-pointer"
                            >
                              查看 Payload
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
    </>
  );
}
