import { createTenant, saveTenantConfig } from "db";
import { type NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const {
      businessId,
      name,
      planTier = "free",
      systemPrompt,
      welcomeMessage,
    } = body;

    if (!businessId || !name) {
      return NextResponse.json(
        { success: false, error: "businessId and name are required" },
        { status: 400 },
      );
    }

    // 1. 创建租户主体
    const tenant = await createTenant({
      businessId: businessId.toLowerCase().trim(),
      name: name.trim(),
      planTier,
    });

    // 2. 初始化初始草稿配置
    const config = await saveTenantConfig({
      businessId: tenant.businessId,
      systemPrompt:
        systemPrompt ||
        `You are the professional AI customer service assistant for ${name}. Assist customers with order status, returns, and store policy queries politely and efficiently.`,
      welcomeMessage:
        welcomeMessage ||
        `您好！欢迎联系【${name}】客户服务。我是您的智能客服助手，请问有什么可以帮您的？`,
      temperature: 0.7,
      status: "draft",
    });

    return NextResponse.json({
      success: true,
      tenant,
      config,
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error during tenant onboarding:", error);
    return NextResponse.json(
      { success: false, error: errMsg },
      { status: 500 },
    );
  }
}
