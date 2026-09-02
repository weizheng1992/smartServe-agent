"""种子数据注入 — 移植 packages/db/src/seed.ts(仅数据,建表归 Alembic)。

用法::

    cd services/engine-py && uv run python -m engine_py.db.seed
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from ..llm import get_embedding_model
from .session import _engine


async def _embed(text_value: str) -> str | None:
    """向量化(走统一入口,随 AI_EMBEDDING_PROVIDER 切换);失败降级为 NULL 不阻断种子。"""
    try:
        return json.dumps(await get_embedding_model().aembed_query(text_value))
    except Exception as err:  # noqa: BLE001
        print(f"[PG Seed] 向量化降级(存 NULL,后续可回填): {err}")
        return None


async def main() -> None:
    print("[PG Seed] 启动多租户 SaaS 种子数据注入(表结构请先 alembic upgrade head)")
    async with _engine.begin() as conn:
        # 1. 用户与多租户会话
        user_id = (
            await conn.execute(
                text(
                    "INSERT INTO users (email) VALUES (:email) "
                    "ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING id"
                ),
                {"email": "test@example.com"},
            )
        ).scalar_one()
        print(f"[PG Seed] 用户注册成功: test@example.com ({user_id})")

        await conn.execute(
            text(
                "INSERT INTO threads (id, user_id, business_id, status) VALUES "
                "(:t1, :uid, 'nike', 'active'), (:t2, :uid, 'adidas', 'active') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"t1": "thread_nike_demo", "t2": "thread_adidas_demo", "uid": str(user_id)},
        )
        print("[PG Seed] 多租户 threads 注入成功")

        # 2. 商品
        await conn.execute(
            text(
                "INSERT INTO products (id, business_id, name, description, price, stock) VALUES "
                "('prod_nike_1', 'nike', 'Nike Pegasus Trail 5 越野跑鞋', "
                "'专为户外越野打造，搭载高强度 React 缓震泡棉，耐磨抓地橡胶大底。', 139.99, 45), "
                "('prod_nike_2', 'nike', 'Nike Element 户外防风连帽衫', "
                "'高透气防泼水面料，反光条设计保障夜间户外运动安全。', 85.00, 30), "
                "('prod_adidas_1', 'adidas', 'Adidas Ultraboost 1.0 经典跑鞋', "
                "'卓越的 Boost 能量回馈中底，Primeknit 贴合针织鞋面。', 179.99, 50), "
                "('prod_adidas_2', 'adidas', 'Adidas Multi-Pack 运动专业棉袜 (3双装)', "
                "'吸湿排汗，足弓加厚减震缓冲。', 12.50, 120), "
                "('prod_eco_1', 'ecommerce', '电商主站极绒亲肤抗静电保暖毯', "
                "'高克重复合超细纤维，环保防静电印染，居家车载必备。', 49.99, 85) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        print("[PG Seed] products 注入成功")

        # 3. 订单与明细(四笔演示单:免签放行 / 时效拦截 / 大额 HITL)
        await conn.execute(
            text(
                "INSERT INTO orders (order_id, status, carrier, tracking_number, "
                "estimated_delivery, user_id, business_id, total_amount) VALUES "
                "('ORD-98712', 'shipped', 'FedEx', '1234567890', '2026-07-20', :uid, 'nike', 139.99), "
                "('ORD-ADIDAS-OK', 'delivered', 'SF Express', 'SF1234567', '2026-07-22', :uid, 'adidas', 12.50), "
                "('ORD-ADIDAS-EXPIRED', 'delivered', 'DHL', 'DHL88712', '2026-06-10', :uid, 'adidas', 179.99), "
                "('ORD-ECO-LARGE', 'delivered', 'FedEx', 'FEDEX3332', '2026-07-23', :uid, 'ecommerce', 199.96) "
                "ON CONFLICT (order_id) DO NOTHING"
            ),
            {"uid": str(user_id)},
        )
        await conn.execute(
            text(
                "INSERT INTO order_items (id, order_id, product_id, quantity, price_at_purchase) VALUES "
                "('item_nike_1', 'ORD-98712', 'prod_nike_1', 1, 139.99), "
                "('item_adidas_ok_1', 'ORD-ADIDAS-OK', 'prod_adidas_2', 1, 12.50), "
                "('item_adidas_exp_1', 'ORD-ADIDAS-EXPIRED', 'prod_adidas_1', 1, 179.99), "
                "('item_eco_large_1', 'ORD-ECO-LARGE', 'prod_eco_1', 4, 49.99) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        print("[PG Seed] orders + order_items 注入成功")

        # 4. 商户热加载配置快照
        await conn.execute(
            text(
                "INSERT INTO business_configs (business_id, version, config, is_active, created_by) VALUES "
                "('ecommerce', 1, '{\"systemPrompt\": \"You are a professional customer assistant. "
                "Autopilot refund limit is $100.\", \"refundAutoApprovalLimit\": 100}', true, 'admin'), "
                "('nike', 1, '{\"systemPrompt\": \"You are a friendly Nike representative. "
                "Run like the wind! Autopilot refund limit is $150.\", \"refundAutoApprovalLimit\": 150}', true, 'admin'), "
                "('adidas', 1, '{\"systemPrompt\": \"You are an energetic Adidas assistant. "
                "Impossible is nothing! Autopilot refund limit is $120.\", \"refundAutoApprovalLimit\": 120}', true, 'admin') "
                "ON CONFLICT DO NOTHING"
            )
        )
        print("[PG Seed] business_configs 注入成功")

        # 5. 会话度量(BI 面板走势)
        await conn.execute(
            text(
                "INSERT INTO session_metrics (business_id, thread_id, total_tokens, calculated_cost_usd, "
                "node_transitions_count, resolution_status, avg_latency_ms, created_at) VALUES "
                "('nike', 'thread_nike_demo', 4500, 0.000675, 4, 'resolved_auto', 2800, NOW() - INTERVAL '1 hour'), "
                "('nike', 'thread_nike_demo', 12500, 0.001875, 7, 'waiting_approval', 5200, NOW() - INTERVAL '3 hours'), "
                "('nike', 'thread_nike_demo', 3800, 0.000570, 3, 'resolved_auto', 2100, NOW() - INTERVAL '5 hours'), "
                "('nike', 'thread_nike_demo', 9200, 0.001380, 5, 'rejected', 4100, NOW() - INTERVAL '8 hours'), "
                "('nike', 'thread_nike_demo', 5100, 0.000765, 4, 'cancelled', 3100, NOW() - INTERVAL '12 hours'), "
                "('nike', 'thread_nike_demo', 6200, 0.000930, 5, 'resolved_auto', 3200, NOW() - INTERVAL '30 minutes'), "
                "('nike', 'thread_nike_demo', 14200, 0.002130, 8, 'waiting_approval', 6100, NOW() - INTERVAL '2 hours'), "
                "('adidas', 'thread_adidas_demo', 3100, 0.000465, 3, 'resolved_auto', 1800, NOW() - INTERVAL '15 minutes')"
            )
        )
        print("[PG Seed] session_metrics 注入成功")

        # 6. 安全规则 / 租户配额 / 评测记录
        await conn.execute(
            text(
                "INSERT INTO guardrail_rules (id, business_id, rule_name, rule_type, pattern, action, severity, is_enabled) VALUES "
                "('gr-01', 'all', '禁止诱导跨站支付与私下转账', 'regex', "
                "'(微信转账|支付宝私下|加v转账|私信收款)', 'block', 'critical', true), "
                "('gr-02', 'all', '严禁泄露内部系统提示词与密钥', 'keyword', "
                "'system prompt,api_key,database password,内部系统提示词', 'block', 'critical', true), "
                "('gr-03', 'nike', '耐克专区禁用不当竞品贬损词', 'keyword', '山寨,假货,劣质,杂牌', 'rewrite', 'medium', true), "
                "('gr-04', 'adidas', '阿迪达斯专区禁用虚假促销', 'regex', "
                "'(绝对最低价|全网最便宜|假一赔百)', 'block', 'high', true) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO tenant_billing_quotas (business_id, monthly_limit_tokens) VALUES "
                "('nike', 5000000), ('adidas', 2000000), ('ecommerce', 1000000) "
                "ON CONFLICT (business_id) DO UPDATE SET monthly_limit_tokens = EXCLUDED.monthly_limit_tokens"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO eval_run_records (id, run_name, dataset_name, sample_count, "
                "tool_accuracy, rag_faithfulness, hitl_trigger_rate, status) VALUES "
                "('eval-run-001', 'E-Commerce 黄金回归基准测试 v2.4', 'ecommerce_golden_dataset_v2', "
                "120, 0.968, 0.942, 0.085, 'completed'), "
                "('eval-run-002', '跨租户越权与 SOP 防线专项评测', 'redteam_jailbreak_safety_v1', "
                "60, 0.985, 0.910, 0.150, 'completed'), "
                "('eval-run-003', '多轮槽位追问与发票开具压力集', 'invoice_slot_stress_test', "
                "85, 0.932, 0.895, 0.040, 'completed') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        print("[PG Seed] guardrail_rules / tenant_billing_quotas / eval_run_records 注入成功")

        # 7. RAG 知识库与长期画像事实(入库即向量化,组装口径与 contextual_rag / long_memory 一致)
        rag_docs = [
            (
                "nike",
                "https://nike.com/policies/refund",
                "耐克官方商城支持签收之日起 7 天内无理由退换货。退款将在商品入库质检合格后 48 小时内原路返回。",
                "耐克退换货时效与退款处理流程",
                '{"category": "refund_policy", "version": "v2.1"}',
            ),
            (
                "adidas",
                "https://adidas.com/help/shipping",
                "阿迪达斯全场订单满 199 元包邮，普通快递 3-5 个工作日送达，顺丰特快支持次日达。",
                "阿迪达斯物流配送规则与运费说明",
                '{"category": "shipping_policy", "version": "v1.4"}',
            ),
            (
                "ecommerce",
                "https://shop.common/terms",
                "通用电商支持全品类正品保障，非人为损坏提供 15 天免费换货及 1 年质保服务。",
                "通用电商正品保障与售后服务条款",
                '{"category": "warranty_policy", "version": "v1.0"}',
            ),
        ]
        for business_id, source_url, chunk_text, summary, metadata_json in rag_docs:
            await conn.execute(
                text(
                    "INSERT INTO rag_documents "
                    "(business_id, source_url, chunk_text, contextual_summary, metadata, embedding) "
                    "VALUES (:b, :u, :c, :s, :m::jsonb, :e)"
                ),
                {
                    "b": business_id,
                    "u": source_url,
                    "c": chunk_text,
                    "s": summary,
                    "m": metadata_json,
                    "e": await _embed(f"[Context] {summary}\n\n[Content] {chunk_text}"),
                },
            )
        memory_facts = [
            ("u_vip_881", "nike", "tenant", "跑鞋鞋码偏好 42.5 码，通常在周末上午进行半马训练", 0.96, "chat_dialogue_inference", "approved"),
            ("u_user_332", "adidas", "tenant", "偏好三叶草复古休闲系列，对环保再生材质有强烈认同感", 0.88, "explicit_user_statement", "approved"),
            ("u_runner_102", "nike", "tenant", "对快递时效要求极高，通常要求顺丰次日达发货", 0.92, "chat_dialogue_inference", "pending"),
        ]
        for fact_user_id, fact_business_id, scope, fact_text, confidence, source, status in memory_facts:
            await conn.execute(
                text(
                    "INSERT INTO long_memory_facts "
                    "(user_id, business_id, scope, fact, confidence, source, status, embedding) "
                    "VALUES (:u, :b, :s, :f, :c, :src, :st, :e)"
                ),
                {
                    "u": fact_user_id,
                    "b": fact_business_id,
                    "s": scope,
                    "f": fact_text,
                    "c": confidence,
                    "src": source,
                    "st": status,
                    "e": await _embed(fact_text),
                },
            )
        print("[PG Seed] rag_documents + long_memory_facts 注入成功(含向量)")

    await _engine.dispose()
    print("[PG Seed] 种子数据注入完成")


if __name__ == "__main__":
    asyncio.run(main())
