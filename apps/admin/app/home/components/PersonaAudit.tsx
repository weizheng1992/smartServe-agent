import type React from 'react';
import { CheckCircle2, Sparkles, XCircle } from 'ui';
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
        <span className="text-[10px] font-mono text-slate-500 uppercase">SaaS Autonomous User Profile Audit</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left: Pending review cards */}
        <div className="lg:col-span-7 bg-slate-900/40 border border-slate-800 rounded-2xl p-6 space-y-4">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest font-mono">
            ⏳ 待核签消费者事实画像 ({pendingPrefs.length})
          </h3>

          {pendingPrefs.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-xs font-mono space-y-2">
              <CheckCircle2 className="h-8 w-8 text-emerald-500/60 mx-auto" />
              <p>没有待处理的置信度审计工单，全部画像已平稳运行！</p>
            </div>
          ) : (
            <div className="space-y-3 max-h-[450px] overflow-y-auto pr-2">
              {pendingPrefs.map((pref) => {
                const pct = Math.round(pref.confidence * 100);
                const isHigh = pref.confidence >= 0.85;
                const isMid = pref.confidence >= 0.6 && pref.confidence < 0.85;

                return (
                  <div
                    key={pref.id}
                    className="bg-slate-900 border border-slate-800 hover:border-slate-700 p-4 rounded-xl space-y-3.5 transition"
                  >
                    <div className="flex justify-between items-start gap-4">
                      <div className="space-y-1">
                        <span className="text-[10px] font-mono text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded font-semibold uppercase tracking-wider">
                          {pref.source}
                        </span>
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

                    <div className="flex justify-between items-center text-[10px] pt-1 border-t border-slate-850">
                      <span className="text-slate-500 font-mono">
                        User: <span className="text-slate-400">{pref.userId.substring(0, 8)}...</span>
                      </span>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => handlePreferenceAction(pref.id, 'approve')}
                          className="px-2.5 py-1 rounded bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/10 transition font-bold"
                        >
                          核准写入
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePreferenceAction(pref.id, 'reject')}
                          className="px-2.5 py-1 rounded bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border border-rose-500/10 transition font-bold"
                        >
                          拒绝/废弃
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: History & Verified lists */}
        <div className="lg:col-span-5 bg-slate-900/40 border border-slate-800 rounded-2xl p-6 space-y-4">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest font-mono">
            ✅ 已归档/生效消费者特征 ({archivedPrefs.length})
          </h3>

          <div className="space-y-2.5 max-h-[450px] overflow-y-auto pr-2">
            {archivedPrefs.length === 0 ? (
              <div className="py-12 text-center text-slate-500 text-xs font-mono">暂无已归档生效的用户画像数据。</div>
            ) : (
              archivedPrefs.map((pref) => {
                return (
                  <div
                    key={pref.id}
                    className="bg-slate-950/60 border border-slate-850 p-3 rounded-lg flex justify-between items-center gap-4 text-xs hover:border-slate-800 transition"
                  >
                    <div className="space-y-1 leading-relaxed">
                      <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
                        <span
                          className={`text-[9px] font-bold px-1.5 py-0.2 rounded ${
                            pref.status === 'approved'
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/10'
                              : 'bg-rose-500/10 text-rose-400 border border-rose-500/10'
                          }`}
                        >
                          {pref.status === 'approved' ? '已核准' : '已驳回'}
                        </span>
                        <span className="text-[9px] font-mono text-slate-500">{pref.userId.substring(0, 8)}...</span>
                      </div>
                      <p className="text-slate-300 font-medium font-sans">&quot;{pref.fact}&quot;</p>
                    </div>

                    <button
                      type="button"
                      onClick={() => handlePreferenceAction(pref.id, 'delete')}
                      className="text-slate-500 hover:text-rose-400 p-1 rounded hover:bg-rose-500/10 transition"
                      title="删除此特征"
                    >
                      <XCircle className="h-4 w-4" />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
