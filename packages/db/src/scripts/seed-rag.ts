import { getDrizzle, ragDocuments } from "db";
import { and, eq } from "drizzle-orm";
import { getEmbeddingModel } from "engine/src/llm/callLLMWithRetry";
import { generateContextualSummary } from "engine/src/rag/contextGenerator";

export async function seedRAGDocuments() {
  const drizzle = getDrizzle();
  if (!drizzle) {
    console.error("[Seed RAG] ❌ 数据库客户端未就绪，终止灌入。");
    return;
  }

  console.log("=================================================");
  console.log("📦 启动 RAG 知识库高级数据灌入 (商店信息/商品知识/操作指南)");
  console.log("=================================================");

  const rawDocs = [
    // === 门店信息 (store_info) ===
    {
      businessId: "nike",
      category: "store_info",
      title: "Nike 淮海中路旗舰店营业时间与线下服务",
      headerPath: "门店信息 > 上海淮海中路店",
      chunkText:
        "Nike 旗舰店（上海淮海中路店）：营业时间为每日 10:00 - 22:00。地址：上海市黄浦区淮海中路 816 号。店内提供现场 3D 步态足型诊断测量、定制烫印及专业跑鞋试跑跑道体验服务。电话：021-64378888。",
    },
    {
      businessId: "adidas",
      category: "store_info",
      title: "Adidas 三里屯概念店营业时间与体验",
      headerPath: "门店信息 > 北京三里屯太古里店",
      chunkText:
        "Adidas 三叶草概念店（北京三里屯太古里）：营业时间为每日 10:00 - 22:30。地址：北京市朝阳区三里屯路 19 号院 1 号楼。提供专属限定球鞋预约抽签取货、专业网球拍拉线服务及体感试衣镜体验。电话：010-64179999。",
    },
    {
      businessId: "ecommerce",
      category: "store_info",
      title: "电商主站客户服务中心与响应时间",
      headerPath: "门店与服务 > 客户服务中心",
      chunkText:
        "电商主站客户服务中心：线上人工客服服务时间为每日 08:00 - 24:00（全年无休）。AI 智能助手提供 7x24 小时全天候无休服务，支持自动退款、物流实时追踪、尺码咨询与发票开具。",
    },

    // === 商品知识 (product_knowledge) ===
    {
      businessId: "nike",
      category: "product_knowledge",
      title: "Nike GORE-TEX 防水鞋保养与洗涤规范",
      headerPath: "商品保养指南 > GORE-TEX 防水越野跑鞋",
      chunkText:
        "Nike GORE-TEX 防水越野跑鞋清洗与保养指南：1. 刷洗前请先拆下鞋带与鞋垫；2. 使用中性洗涤剂与软毛刷轻轻刷洗网面，严禁使用强碱性洗衣粉或漂白水；3. 清洗后置于阴凉通风处自然风干，切勿暴晒或使用烘干机，以免导致 GORE-TEX 防水膜开裂失效。",
    },
    {
      businessId: "adidas",
      category: "product_knowledge",
      title: "Adidas Boost 中底抗氧化与保养说明",
      headerPath: "商品知识 > Boost 科技中底保养",
      chunkText:
        "Adidas Boost 科技中底黄化保养说明：Boost 材料采用热塑性聚氨酯（eTPU）发泡而成，长时间接触紫外线或雨水可能发生正常氧化变黄。建议清洗后涂抹防氧化保护膜，存放时加入防潮剂并避免阳光直射。若轻微变黄，可使用专用补色笔涂抹修复。",
    },
    {
      businessId: "ecommerce",
      category: "product_knowledge",
      title: "纯棉与羊毛织物洗涤防缩水 SOP",
      headerPath: "面料保养 > 纯棉与羊毛织物",
      chunkText:
        "纯棉与羊毛织物防缩水保养 SOP：纯棉打底衫请使用 30℃ 以下冷水机洗或手洗；羊毛衫请使用专用的羊毛洗涤剂，并在洗涤后选择轻柔平铺晾干，禁止挂晒以防衣服拉长变形。",
    },

    // === 操作指南 (operation_guide) ===
    {
      businessId: "ecommerce",
      category: "operation_guide",
      title: "电子发票申请与抬头修改 SOP 流程",
      headerPath: "系统操作指南 > 电子发票开具",
      chunkText:
        "电子发票申请与抬头修改 SOP 流程：1. 进入个人中心 -> 我的订单，点击【申请发票】；2. 选择【企业抬头】或【个人抬头】，输入统一社会信用代码与接收邮箱；3. 系统将在 5 分钟内自动开具电子发票并发送至指定邮箱。如需修改抬头，请在开票前联系客服操作。",
    },
    {
      businessId: "ecommerce",
      category: "operation_guide",
      title: "修改收货地址与配送时间 SOP 流程",
      headerPath: "系统操作指南 > 修改收货地址",
      chunkText:
        "修改收货地址与配送时间 SOP：若订单状态为【待发货】，您可在聊天窗口输入“修改收货地址为 [新地址]”触发自动修改；若订单已进入【已发货】状态，系统将自动联系顺丰/圆通快递员进行转寄，由此产生的转寄费用由用户承担。",
    },
  ];

  const embeddingModel = getEmbeddingModel();

  for (const doc of rawDocs) {
    console.log(`[Seed RAG] 正在处理 [${doc.businessId}] - [${doc.title}]...`);
    const contextualSummary = await generateContextualSummary(
      doc.title,
      doc.headerPath,
      doc.chunkText,
      doc.businessId,
    );

    const combinedText = `[Context] ${contextualSummary}\n\n[Content] ${doc.chunkText}`;
    const embedding = await embeddingModel.embedQuery(combinedText);
    const serializedEmbedding = JSON.stringify(embedding);

    const existing = await drizzle
      .select({ id: ragDocuments.id })
      .from(ragDocuments)
      .where(
        and(
          eq(ragDocuments.businessId, doc.businessId),
          eq(ragDocuments.chunkText, doc.chunkText),
        ),
      )
      .limit(1);

    if (existing.length > 0) {
      await drizzle
        .update(ragDocuments)
        .set({
          contextualSummary,
          embedding: serializedEmbedding,
          metadata: {
            category: doc.category,
            title: doc.title,
            headerPath: doc.headerPath,
            updatedAt: new Date().toISOString(),
          },
        })
        .where(eq(ragDocuments.id, existing[0].id));
      console.log(
        `[Seed RAG] 🔄 已存在切片，更新完成: [${doc.businessId}] - [${doc.title}]`,
      );
    } else {
      await drizzle.insert(ragDocuments).values({
        businessId: doc.businessId,
        chunkText: doc.chunkText,
        contextualSummary,
        embedding: serializedEmbedding,
        metadata: {
          category: doc.category,
          title: doc.title,
          headerPath: doc.headerPath,
          updatedAt: new Date().toISOString(),
        },
      });
      console.log(
        `[Seed RAG] ➕ 新增切片完成: [${doc.businessId}] - [${doc.title}]`,
      );
    }
  }

  console.log("=================================================");
  console.log("✅ RAG 知识库多分类数据填充完成！已成功落盘。");
  console.log("=================================================");
}

if (import.meta.main) {
  seedRAGDocuments()
    .then(() => process.exit(0))
    .catch((err) => {
      console.error("Seed RAG error:", err);
      process.exit(1);
    });
}
