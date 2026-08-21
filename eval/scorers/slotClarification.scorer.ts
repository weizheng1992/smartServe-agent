export default function (output: string, context: any) {
  try {
    const { expectedMissingSlots, expectedIntent, expectClarification } =
      context.vars || {};

    let parsed: any;
    try {
      parsed = JSON.parse(output);
    } catch {
      const match = output.match(/\{[\s\S]*\}/) || output.match(/\[[\s\S]*\]/);
      if (match) {
        parsed = JSON.parse(match[0]);
      } else {
        // Natural language response check
        if (expectClarification) {
          const pass =
            output.includes("订单") ||
            output.includes("地址") ||
            output.includes("单号");
          return {
            pass,
            score: pass ? 1.0 : 0.0,
            reason: pass
              ? "Successfully triggered slot clarification prompt"
              : "Failed to provide clarification prompt",
          };
        }
        return { pass: false, score: 0.0, reason: "Output is not valid JSON" };
      }
    }

    const taskSpec = parsed.taskSpec || parsed[0]?.taskSpec;
    let intent = parsed.intentType || parsed.intent || parsed[0]?.intent;

    if (intent === "refund" && expectedIntent === "order_return")
      intent = "order_return";
    if (intent === "order_status" && expectedIntent === "order_query")
      intent = "order_query";

    if (expectedIntent && intent !== expectedIntent) {
      return {
        pass: false,
        score: 0.0,
        reason: `Expected intent ${expectedIntent}, but received ${intent}`,
      };
    }

    if (expectedMissingSlots) {
      const missing = taskSpec?.missingSlots || parsed.missingSlots || [];
      const expectedArray = Array.isArray(expectedMissingSlots)
        ? expectedMissingSlots
        : [expectedMissingSlots];
      const hasAllExpected = expectedArray.every((s: string) =>
        missing.includes(s),
      );
      if (!hasAllExpected) {
        return {
          pass: false,
          score: 0.5,
          reason: `Missing slots mismatch: expected [${expectedArray.join(", ")}], got [${missing}]`,
        };
      }
    }

    return {
      pass: true,
      score: 1.0,
      reason: "Slot extraction and clarification state validated successfully",
    };
  } catch (err: any) {
    return {
      pass: false,
      score: 0.0,
      reason: `Error in slotClarification scorer: ${err.message}`,
    };
  }
}
