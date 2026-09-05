#!/usr/bin/env bash
# [DEBUG-rfnd] Phase-1 feedback loop: 商户退款 → admin 审批通过 → 店铺订单状态变化
#
# 用法: ./refund-approval-e2e.sh [ORDER_ID]
# 红灯 = 审批通过后 merchant_orders.status 仍未变为 REFUNDED(用户症状:店铺没反应)
# 绿灯 = 订单状态在审批后 90s 内变为 REFUNDED
#
# 前置: gateway(4000) / shared-postgres / shared-redis 运行中

set -uo pipefail

ORDER_ID="${1:-AURORA-ORD-2026-9081}"
BASE="${BASE:-http://localhost:4000}"
STAMP="$(date +%s)"
THREAD="merchant_thread_CUST-8801_aurora_dbg_${STAMP}"   # 每轮独立线程,免清理旧工单
PASS=0

psql_merchant() { docker exec shared-postgres psql -U agent_user -d agent_merchant -tA -c "$1"; }
psql_engine()   { docker exec shared-postgres psql -U agent_user -d agent_platform -tA -c "$1"; }

echo "== [0] 重置订单状态: $ORDER_ID -> PAID"
psql_merchant "UPDATE merchant_orders SET status='PAID' WHERE order_id='$ORDER_ID';"
psql_engine   "DELETE FROM orders WHERE order_id='$ORDER_ID';"   # 清 engine 侧残留(防 double-refund 误判)
echo "    before: $(psql_merchant "SELECT status FROM merchant_orders WHERE order_id='$ORDER_ID';")"

echo "== [1] 门店聊天发起退款 (thread=$THREAD)"
curl -s -m 180 -X POST "$BASE/api/store/chat" -H 'Content-Type: application/json' \
  -d "{\"businessId\":\"aurora\",\"userId\":\"CUST-8801\",\"threadId\":\"$THREAD\",\"message\":\"帮我申请订单 $ORDER_ID 的全额退款，商品质量问题\"}" \
  | jq -r '"    success=\(.success) output=\(.output[:160])"'

echo "== [2] 查询 waiting 审批工单"
APPROVAL_ID="$(curl -s "$BASE/api/admin/approvals?tenantId=aurora&status=waiting" \
  | jq -r --arg oid "$ORDER_ID" --arg th "$THREAD" '.approvals[]
      | select(.actionPayload.args.orderId == $oid and .threadId == $th) | .id' | head -1)"
if [ -z "$APPROVAL_ID" ]; then
  echo "RED: 未找到 $ORDER_ID 的 waiting 审批工单(引擎未挂起?)"
  exit 1
fi
echo "    approvalId=$APPROVAL_ID"

echo "== [3] admin 审批通过"
curl -s -m 30 -X POST "$BASE/api/admin/approvals" -H 'Content-Type: application/json' \
  -d "{\"approvalId\":\"$APPROVAL_ID\",\"action\":\"approve\"}" | jq -c .

echo "== [4] 轮询店铺订单状态 (最长 90s)"
for i in $(seq 1 30); do
  sleep 3
  ST="$(psql_merchant "SELECT status FROM merchant_orders WHERE order_id='$ORDER_ID';")"
  if [ "$ST" = "REFUNDED" ]; then PASS=1; break; fi
done

echo "== [5] 结果"
echo "    merchant_orders.status = $ST"
echo "    outbox 事件: $(psql_engine "SELECT status || ' | ' || coalesce(left(error_message,100),'-') FROM approval_outbox_events WHERE approval_id='$APPROVAL_ID' ORDER BY created_at DESC LIMIT 1;")"

if [ "$PASS" = "1" ]; then
  echo "GREEN: 审批通过后店铺订单已退款"
  exit 0
else
  echo "RED: 审批通过后店铺订单无变化(用户症状复现)"
  exit 1
fi
