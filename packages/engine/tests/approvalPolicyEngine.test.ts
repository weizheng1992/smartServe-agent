import { describe, expect, test } from "bun:test";
import { ApprovalPolicyEngine } from "../src/graph/nodes/approvalPolicyEngine";

describe("ApprovalPolicyEngine Unit Tests", () => {
  test("Should evaluate auto-approval limits correctly", async () => {
    // $50 <= $100 limit -> Auto Approve
    const passResult = await ApprovalPolicyEngine.evaluateRefundAutoApproval(
      undefined,
      "50.00",
      100,
    );
    expect(passResult.shouldAutoApprove).toBe(true);
    expect(passResult.groundedAmount).toBe(50);

    // $150 > $100 limit -> Require Approval
    const rejectResult = await ApprovalPolicyEngine.evaluateRefundAutoApproval(
      undefined,
      "150.00",
      100,
    );
    expect(rejectResult.shouldAutoApprove).toBe(false);
    expect(rejectResult.groundedAmount).toBe(150);
  });

  test("Should evaluate address change policies safely", async () => {
    // Non-existent or empty orderId returns default safe result
    const result =
      await ApprovalPolicyEngine.evaluateAddressChangePolicy(undefined);
    expect(result.isHighValue).toBe(false);
  });

  test("Should handle double refund check safely for non-existent order", async () => {
    const doubleCheck =
      await ApprovalPolicyEngine.checkDoubleRefund("NON_EXISTENT_ORD");
    expect(doubleCheck.isDoubleRefund).toBe(false);
  });
});
