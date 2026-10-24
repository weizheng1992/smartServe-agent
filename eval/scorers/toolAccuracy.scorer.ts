export default function (output: string, context: any) {
  try {
    const expectedTools = context.vars.expectedTools;
    if (!expectedTools) {
      return {
        pass: true,
        score: 1.0,
        reason: 'No expected tools defined to validate',
      };
    }

    // "none":irrelevance 负例 —— 断言零业务工具派发(04 号票)
    const expectNone = String(expectedTools) === 'none';

    let expectedToolsArray: string[] = [];
    if (typeof expectedTools === 'string') {
      try {
        const parsed = JSON.parse(expectedTools);
        if (Array.isArray(parsed)) {
          expectedToolsArray = parsed.map((s: any) => String(s).trim());
        } else {
          expectedToolsArray = expectedTools
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean);
        }
      } catch {
        expectedToolsArray = expectedTools
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean);
      }
    } else if (Array.isArray(expectedTools)) {
      expectedToolsArray = expectedTools.flat().map((s: any) => String(s).trim());
    }

    let parsed: any;
    try {
      parsed = JSON.parse(output);
    } catch {
      const match = output.match(/\{[\s\S]*\}/) || output.match(/\[[\s\S]*\]/);
      if (match) {
        parsed = JSON.parse(match[0]);
      } else {
        return { pass: false, score: 0.0, reason: 'Output is not valid JSON' };
      }
    }

    if (expectNone) {
      const called: string[] = Array.isArray(parsed.calledTools) ? parsed.calledTools : [];
      return called.length === 0
        ? { pass: true, score: 1.0, reason: '零业务工具派发(符合预期)' }
        : { pass: false, score: 0.0, reason: `应零业务派发却调用: ${called.join(', ')}` };
    }

    if (Array.isArray(parsed.calledTools)) {
      // 真跑轨迹(04 号票):provider 端到端 run_agent 终态提取,HITL 挂起
      // 步按已派发计权 —— 集合断言(期望集全命中,容纳合法路径多样性)
      const calledReal: string[] = parsed.calledTools.map((s: any) => String(s));
      const matchedReal = expectedToolsArray.every((t: string) => calledReal.includes(t));
      return matchedReal
        ? { pass: true, score: 1.0, reason: `实际调用覆盖期望集: [${calledReal.join(', ')}]` }
        : {
            pass: false,
            score: 0.0,
            reason: `Tool mismatch. Expected: [${expectedToolsArray.join(', ')}], Called: [${calledReal.join(', ')}]`,
          };
    }

    // legacy 嗅探保底(planner 分册:llm_provider 直连提示词,subtasks 描述形态)
    const calledTools: string[] = [];
    if (parsed.subtasks) {
      for (const st of parsed.subtasks) {
        const desc = (st.description || '').toLowerCase();
        if (desc.includes('getorderstatus') || desc.includes('order status') || desc.includes('tracking')) {
          calledTools.push('getOrderStatus');
        } else if (desc.includes('processrefund') || desc.includes('refund')) {
          calledTools.push('processRefund');
        } else if (desc.includes('takescreenshot') || desc.includes('screenshot')) {
          calledTools.push('takeScreenshot');
        } else if (desc.includes('listuserorders') || desc.includes('list orders') || desc.includes('other orders')) {
          calledTools.push('listUserOrders');
        } else if (
          desc.includes('queryproductranking') ||
          desc.includes('product ranking') ||
          desc.includes('ranking') ||
          desc.includes('sales ranking') ||
          desc.includes('product analysis') ||
          desc.includes('best seller')
        ) {
          calledTools.push('queryProductRanking');
        }
      }
    }

    const matched = expectedToolsArray.every((t: string) => calledTools.includes(t));
    if (matched) {
      return {
        pass: true,
        score: 1.0,
        reason: `Successfully called all expected tools: ${expectedToolsArray.join(', ')}`,
      };
    }
    return {
      pass: false,
      score: 0.0,
      reason: `Tool mismatch. Expected: [${expectedToolsArray.join(', ')}], Called: [${calledTools.join(', ')}]`,
    };
  } catch (err: any) {
    return {
      pass: false,
      score: 0.0,
      reason: `Error in toolAccuracy scorer: ${err.message}`,
    };
  }
}
