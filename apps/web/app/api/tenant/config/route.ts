import { getTenantConfig, saveTenantConfig } from "db";
import { type NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const businessId = searchParams.get("businessId") || "ecommerce";
    const status =
      (searchParams.get("status") as "draft" | "published") || "published";

    const config = await getTenantConfig(businessId, status);
    return NextResponse.json({
      success: true,
      config,
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error fetching tenant config:", error);
    return NextResponse.json(
      { success: false, error: errMsg },
      { status: 500 },
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const {
      businessId,
      systemPrompt,
      welcomeMessage,
      temperature,
      status = "draft",
    } = body;

    if (!businessId) {
      return NextResponse.json(
        { success: false, error: "businessId is required" },
        { status: 400 },
      );
    }

    const updated = await saveTenantConfig({
      businessId,
      systemPrompt,
      welcomeMessage,
      temperature,
      status,
    });

    return NextResponse.json({
      success: true,
      config: updated,
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error saving tenant config:", error);
    return NextResponse.json(
      { success: false, error: errMsg },
      { status: 500 },
    );
  }
}
