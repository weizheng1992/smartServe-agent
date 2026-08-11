import { db } from "db";
import { type NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const { email } = await req.json();
    if (!email || !email.includes("@")) {
      return NextResponse.json(
        { success: false, error: "请输入有效的邮箱地址" },
        { status: 400 },
      );
    }

    const user = await db.findOrCreateUserByEmail(email);
    return NextResponse.json({ success: true, user });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error("[API Login Error]:", err);
    return NextResponse.json(
      { success: false, error: errMsg },
      { status: 500 },
    );
  }
}
