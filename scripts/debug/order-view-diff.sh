#!/usr/bin/env bash
# [DEBUG-ordview] 反馈回路:验证 商户聊天查单视图 == 订单列表页视图
#
# 用法: ./order-view-diff.sh [customerId ...]   (默认 CUST-8801 CUST-8802 CUST-8803)
# 判定:
#   LIST  = GET  /api/store/orders?customerId=$UID            (订单列表页数据源)
#   CHAT  = POST /api/store/chat "查询我的订单记录"            (聊天卡片中的 orderId 集合)
#   两集合不一致 => RED (复现用户症状:聊天查单与订单列表展示不一样)
set -uo pipefail
GATEWAY="${GATEWAY:-http://localhost:4000}"
USERS=("$@")
if [ ${#USERS[@]} -eq 0 ] || [ -z "${USERS[0]}" ]; then USERS=(CUST-8801 CUST-8802 CUST-8803); fi

overall=0
for uid in "${USERS[@]}"; do
  echo "===== user: $uid ====="

  list_json=$(curl -s -m 15 "$GATEWAY/api/store/orders?customerId=$uid")
  list_ids=$(echo "$list_json" | jq -r '[.orders[]?.orderId] | sort | unique | .[]' | tr '\n' ' ')
  echo "LIST  (${#list_json} bytes): $list_ids"

  chat_json=$(curl -s -m 180 -X POST "$GATEWAY/api/store/chat" \
    -H 'Content-Type: application/json' \
    -d "{\"message\":\"查询一下我的订单记录\",\"threadId\":\"debug_diff_v2_$uid\",\"userId\":\"$uid\",\"businessId\":\"aurora\",\"routeContext\":{\"pathname\":\"/orders\"}}")
  # 卡片是确定性载体:order_card/order_picker 携带全部 orderId;文本兜底
  chat_card_ids=$(echo "$chat_json" | jq -r '[.. | objects | .orderId? // empty] | sort | unique | .[]' | tr '\n' ' ')
  chat_text=$(echo "$chat_json" | jq -r '.output // .result // ""')
  chat_text_ids=$(echo "$chat_text" | grep -oE '[A-Za-z0-9]+-ORD-[A-Za-z0-9-]+|ORD-[A-Za-z0-9-]+' | sort -u | tr '\n' ' ')
  echo "CHAT  cards: $chat_card_ids"
  echo "CHAT  text : ${chat_text:0:200}"
  echo "CHAT  text_ids: $chat_text_ids"

  if [ -z "$chat_card_ids" ] && [ -z "$chat_text_ids" ]; then
    if [ -z "$(echo "$list_ids" | tr -d ' ')" ]; then
      echo "RESULT: GREEN (两侧均为空——一致地『暂无订单』)"
    else
      echo "RESULT: RED (列表页有订单但聊天未返回任何订单标识)"
      overall=1
    fi
    continue
  fi

  # 以卡片为准;无卡片时退回文本
  chat_set="${chat_card_ids:-$chat_text_ids}"
  diff_out=$(diff <(echo "$list_ids" | tr ' ' '\n' | grep -c .) <(echo "$chat_set" | tr ' ' '\n' | grep -c .) >/dev/null \
    && comm -3 <(echo "$list_ids" | tr ' ' '\n' | grep . | sort) <(echo "$chat_set" | tr ' ' '\n' | grep . | sort) || true)
  only_list=$(comm -23 <(echo "$list_ids" | tr ' ' '\n' | grep . | sort -u) <(echo "$chat_set" | tr ' ' '\n' | grep . | sort -u) | tr '\n' ' ')
  only_chat=$(comm -13 <(echo "$list_ids" | tr ' ' '\n' | grep . | sort -u) <(echo "$chat_set" | tr ' ' '\n' | grep . | sort -u) | tr '\n' ' ')

  if [ -z "$only_list" ] && [ -z "$only_chat" ]; then
    echo "RESULT: GREEN (两视图订单集合一致)"
  else
    echo "RESULT: RED"
    [ -n "$only_chat" ] && echo "  仅聊天可见(列表页没有): $only_chat"
    [ -n "$only_list" ] && echo "  仅列表页可见(聊天没提到): $only_list"
    overall=1
  fi
done
echo "====="
[ "$overall" -eq 0 ] && echo "OVERALL: GREEN" || echo "OVERALL: RED"
exit "$overall"
