#!/usr/bin/env python3
"""全意图矩阵实弹测试(客服对话链路)。"""
import json, urllib.request

BASE = "http://localhost:4000/api/store/chat"
MATRIX = [
    ("优惠查询",     "有什么优惠活动"),
    ("优惠券查询",   "我的优惠券有哪些"),
    ("满减咨询",     "满减怎么算"),
    ("订单查询",     "查一下订单 AURORA-ORD-2026-9081"),
    ("导购推荐",     "推荐一件冲锋衣"),
    ("退货行为",     "我要退货退款"),
    ("地址管理",     "帮我新增一个收货地址"),
    ("购物车操作",   "看看我的购物车"),
    ("会话指标",     "AI 自动解决率多少"),
    ("商品促销价",   "冲锋衣88折是真的吗"),
]
MULTI = [
    ("订单 + 优惠",   "查一下订单9081 顺便看看有什么优惠券"),
    ("退货 + 导购",   "退了这单 然后推荐个冲锋衣"),
    ("订单 + 物流",   "订单9081到哪了 物流信息也给我"),
    ("三意图",        "查订单 看优惠券 再推荐个背包"),
]

def ask(message, user_id="CUST-8801"):
    req = urllib.request.Request(BASE, data=json.dumps({
        "message": message, "userId": user_id, "businessId": "aurora",
    }).encode(), headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
    return str(d.get("output") or "")

def run(cases, label):
    print(f"\n{label}\n{'-' * 40}")
    real, degraded = 0, 0
    for lbl, q in cases:
        out = ask(q)
        canned = "客服系统处理" in out or "上游模型波动" in out
        if canned:
            degraded += 1
            print(f"  △ [{lbl}] {q} → 降级")
        else:
            real += 1
            print(f"  ✓ [{lbl}] {q} → {out[:80]}")

if __name__ == "__main__":
    run(MATRIX, "全意图矩阵")
    run(MULTI, "多意图联合")
    print("完成")
