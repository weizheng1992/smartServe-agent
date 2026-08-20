import type React from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CheckCircle2,
  ScrollArea,
  Sparkles,
  XCircle,
} from 'ui';
import type { PreferenceFact } from '../hooks/types';

interface PersonaAuditProps {
  selectedMerchant: string;
  preferences: PreferenceFact[];
  handlePreferenceAction: (preferenceId: string, action: 'approve' | 'reject' | 'delete') => Promise<void>;
}

export function PersonaAudit({ selectedMerchant, preferences, handlePreferenceAction }: PersonaAuditProps) {
  const pendingPrefs = preferences.filter((p) => p.businessId === selectedMerchant && p.status === 'pending');
  const archivedPrefs = preferences.filter((p) => p.businessId === selectedMerchant && p.status !== 'pending');

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Sparkles className="h-5 w-5 text-indigo-400 animate-pulse" />
          <h2 className="text-sm font-bold tracking-wider uppercase text-slate-300">
            🧠 智能画像专家多租户动态审计核签中心 ({preferences.filter((p) => p.businessId === selectedMerchant).length}
            )
          </h2>
        </div>
        <Badge variant="outline" className="text-[10px] font-mono text-slate-500 border-slate-800 uppercase">
          SaaS Autonomous User Profile Audit
        </Badge>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left: Pending review cards */}
        <Card className="lg:col-span-7 bg-slate-900/40 border-slate-800 p-6 space-y-4">
          <CardHeader className="p-0 space-y-1 pb-2">
            <CardTitle className="text-xs font-bold text-slate-400 uppercase tracking-widest font-mono">
              ⏳ 待核签消费者事实画像 ({pendingPrefs.length})
            </CardTitle>
          </CardHeader>

          {pendingPrefs.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-xs font-mono space-y-2">
              <CheckCircle2 className="h-8 w-8 text-emerald-500/60 mx-auto" />
              <p>没有待处理的置信度审计工单，全部画像已平稳运行！</p>
            </div>
          ) : (
            <ScrollArea className="max-h-[450px] pr-2">
              <div className="space-y-3">
                {pendingPrefs.map((pref) => {
                  const pct = Math.round(pref.confidence * 100);
                  const isHigh = pref.confidence >= 0.85;
                  const isMid = pref.confidence >= 0.6 && pref.confidence < 0.85;

                  return (
                    <Card
                      key={pref.id}
                      className="bg-slate-900 border-slate-800 hover:border-slate-700 p-4 space-y-3.5 transition"
                    >
                      <div className="flex justify-between items-start gap-4">
                        <div className="space-y-1">
                          <Badge
                            variant="outline"
                            className="text-[10px] font-mono text-indigo-400 bg-indigo-500/10 border-indigo-500/20 font-semibold uppercase"
                          >
                            {pref.source}
                          </Badge>
                          <p className="text-xs text-slate-200 font-medium leading-relaxed">&quot;{pref.fact}&quot;</p>
                        </div>
                        {/* Confidence rating */}
                        <div className="text-right shrink-0">
                          <span
                            className={`text-xs font-mono font-bold ${
                              isHigh ? 'text-emerald-400' : isMid ? 'text-amber-400' : 'text-rose-400'
                            }`}
                          >
                            {pct}%
                          </span>
                          <span className="text-[9px] text-slate-500 block">置信度</span>
                        </div>
                      </div>

                      {/* Confidence Progress Bar */}
                      <div className="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            isHigh ? 'bg-emerald-500' : isMid ? 'bg-amber-500' : 'bg-rose-500'
                          }`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>

                      <div className="flex justify-between items-center text-[10px] pt-1 border-t border-slate-800/80">
                        <span className="text-slate-500 font-mono">
                          User: <span className="text-slate-400">{pref.userId.substring(0, 8)}...</span>
                        </span>
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="default"
                            onClick={() => handlePreferenceAction(pref.id, 'approve')}
                            className="h-7 text-[10px] font-bold bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/20 shadow-none px-2.5"
                          >
                            核准写入
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="destructive"
                            onClick={() => handlePreferenceAction(pref.id, 'reject')}
                            className="h-7 text-[10px] font-bold bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border border-rose-500/20 shadow-none px-2.5"
                          >
                            拒绝/废弃
                          </Button>
                        </div>
                      </div>
                    </Card>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </Card>

        {/* Right: History & Verified lists */}
        <Card className="lg:col-span-5 bg-slate-900/40 border-slate-800 p-6 space-y-4">
          <CardHeader className="p-0 space-y-1 pb-2">
            <CardTitle className="text-xs font-bold text-slate-400 uppercase tracking-widest font-mono">
              ✅ 已归档/生效消费者特征 ({archivedPrefs.length})
            </CardTitle>
          </CardHeader>

          <ScrollArea className="max-h-[450px] pr-2">
            <div className="space-y-2.5">
              {archivedPrefs.length === 0 ? (
                <div className="py-12 text-center text-slate-500 text-xs font-mono">暂无已归档生效的用户画像数据。</div>
              ) : (
                archivedPrefs.map((pref) => {
                  return (
                    <Card
                      key={pref.id}
                      className="bg-slate-950/60 border-slate-800 p-3 flex justify-between items-center gap-4 text-xs hover:border-slate-700 transition"
                    >
                      <div className="space-y-1 leading-relaxed">
                        <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
                          <Badge
                            variant={pref.status === 'approved' ? 'success' : 'destructive'}
                            className="text-[9px] font-bold px-1.5 py-0.2"
                          >
                            {pref.status === 'approved' ? '已核准' : '已驳回'}
                          </Badge>
                          <span className="text-[9px] font-mono text-slate-500">{pref.userId.substring(0, 8)}...</span>
                        </div>
                        <p className="text-slate-300 font-medium font-sans">&quot;{pref.fact}&quot;</p>
                      </div>

                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        onClick={() => handlePreferenceAction(pref.id, 'delete')}
                        className="h-7 w-7 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition"
                        title="删除此特征"
                      >
                        <XCircle className="h-4 w-4" />
                      </Button>
                    </Card>
                  );
                })
              )}
            </div>
          </ScrollArea>
        </Card>
      </div>
    </section>
  );
}
