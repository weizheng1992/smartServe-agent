export default function (output: string, context: any) {
  try {
    const {
      // '[{"scope":"global","pattern":"270|44"},{"scope":"tenant","pattern":"Jordan","minConfidence":0.85}]'
      // 每个条目须有至少一条事实同时满足 scope 与 fact 正则;minConfidence 可选(命中事实置信度须 >= 该值)
      expectFacts,
      // 负对照(寒暄):hasNewPreference=false 或零事实
      expectNoFacts,
      // 模糊表述:不得出现置信度 >= 0.85 的事实(低置信丢弃或 pending)
      forbidApproved,
    } = context.vars || {};

    let parsed: any;
    try {
      parsed = JSON.parse(output);
    } catch {
      return {
        pass: false,
        score: 0.0,
        reason: `Persona audit output is not valid JSON (围栏破产): ${String(output).slice(0, 160)}`,
      };
    }

    const facts: any[] = Array.isArray(parsed.extractedFacts) ? parsed.extractedFacts : [];
    const conf = (f: any) => (f?.confidence == null ? 1 : Number(f.confidence));

    if (expectNoFacts) {
      const pass = parsed.hasNewPreference === false || facts.length === 0;
      return {
        pass,
        score: pass ? 1.0 : 0.0,
        reason: pass
          ? '负对照通过:未产出偏好事实'
          : `寒暄轮误产出 ${facts.length} 条事实: ${JSON.stringify(facts).slice(0, 200)}`,
      };
    }

    if (forbidApproved) {
      const approved = facts.filter((f) => conf(f) >= 0.85);
      const pass = !parsed.hasNewPreference || approved.length === 0;
      return {
        pass,
        score: pass ? 1.0 : 0.0,
        reason: pass
          ? '模糊表述通过:未直接进 approved 档'
          : `模糊表述误出 approved 档 ${approved.length} 条: ${JSON.stringify(approved).slice(0, 240)}`,
      };
    }

    if (expectFacts) {
      const expected = JSON.parse(expectFacts) as Array<{
        scope: string;
        pattern: string;
        minConfidence?: number;
      }>;
      for (const want of expected) {
        const re = new RegExp(want.pattern, 'i');
        const matched = facts.filter((f) => f?.scope === want.scope && re.test(String(f?.fact || '')));
        if (matched.length === 0) {
          return {
            pass: false,
            score: 0.0,
            reason: `未抽出 scope=${want.scope} 且命中 /${want.pattern}/ 的事实;实际: ${JSON.stringify(facts).slice(0, 240)}`,
          };
        }
        if (want.minConfidence != null) {
          const strongest = Math.max(...matched.map(conf));
          if (strongest < want.minConfidence) {
            return {
              pass: false,
              score: 0.5,
              reason: `命中事实置信度不足:期望 >= ${want.minConfidence},实际最高 ${strongest}`,
            };
          }
        }
      }
      return {
        pass: true,
        score: 1.0,
        reason: `抽取断言全过(${expected.length} 个维度,事实 ${facts.length} 条)`,
      };
    }

    return {
      pass: false,
      score: 0.0,
      reason: 'personaExtraction.scorer 需要至少一个断言维度(expectFacts / expectNoFacts / forbidApproved)',
    };
  } catch (err: any) {
    return {
      pass: false,
      score: 0.0,
      reason: `Error in personaExtraction scorer: ${err.message}`,
    };
  }
}
