export default function (output: string, context: any) {
  try {
    const expectedIntents = context.vars.expectedIntents;
    if (!expectedIntents) {
      return { pass: true, score: 1.0, reason: "No expected intents defined to compute F1" };
    }

    let parsed: any;
    try {
      parsed = JSON.parse(output);
    } catch {
      const match = output.match(/\{[\s\S]*\}/) || output.match(/\[[\s\S]*\]/);
      if (match) {
        parsed = JSON.parse(match[0]);
      } else {
        return { pass: false, score: 0.0, reason: "Output is not valid JSON" };
      }
    }

    const predictedIntents: string[] = [];
    if (Array.isArray(parsed)) {
      for (const item of parsed) {
        if (item.intent) predictedIntents.push(item.intent);
      }
    } else if (parsed.intents) {
      for (const item of parsed.intents) {
        if (item.intent) predictedIntents.push(item.intent);
      }
    } else if (typeof parsed === 'object') {
      // In case it's a flat object with single intent
      if (parsed.intent) {
        predictedIntents.push(parsed.intent);
      }
    }

    const predSet = new Set(predictedIntents);
    const expSet = new Set(expectedIntents);

    let tp = 0;
    predSet.forEach((p) => {
      if (expSet.has(p)) tp++;
    });

    const fp = predSet.size - tp;
    const fn = expSet.size - tp;

    if (predSet.size === 0 && expSet.size === 0) {
      return { pass: true, score: 1.0, reason: "Perfect F1 score (no intents expected, none predicted)" };
    }

    const precision = predSet.size > 0 ? tp / predSet.size : 0;
    const recall = expSet.size > 0 ? tp / expSet.size : 0;
    const f1 = (precision + recall) > 0 ? (2 * precision * recall) / (precision + recall) : 0;

    return {
      pass: f1 >= 0.8,
      score: f1,
      reason: `F1 Score: ${f1.toFixed(4)} (Precision: ${precision.toFixed(4)}, Recall: ${recall.toFixed(4)})`,
    };
  } catch (err: any) {
    return { pass: false, score: 0.0, reason: `Error in intentF1 scorer: ${err.message}` };
  }
}
