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

    const matched = expectedTools.every((t: string) => calledTools.includes(t));
    if (matched) {
      return {
        pass: true,
        score: 1.0,
        reason: `Successfully called all expected tools: ${expectedTools.join(', ')}`,
      };
    }
    return {
      pass: false,
      score: 0.0,
      reason: `Tool mismatch. Expected: [${expectedTools.join(', ')}], Called: [${calledTools.join(', ')}]`,
    };
  } catch (err: any) {
    return {
      pass: false,
      score: 0.0,
      reason: `Error in toolAccuracy scorer: ${err.message}`,
    };
  }
}
