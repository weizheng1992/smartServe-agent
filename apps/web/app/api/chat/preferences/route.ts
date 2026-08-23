import { getDrizzle, longMemoryFacts } from 'db';
import { desc, eq, sql } from 'drizzle-orm';
import { type NextRequest, NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

// GET /api/chat/preferences - 获取画像偏好数据，支持按 userId 过滤，并动态关联用户邮箱及最后会话的 business_id
export async function GET(req: NextRequest) {
  try {
    const drizzle = getDrizzle();
    if (!drizzle) {
      return NextResponse.json({ success: true, preferences: [] });
    }

    const { searchParams } = new URL(req.url);
    const filterUserId = searchParams.get('userId');

    let query = sql`
      SELECT
        f.id,
        f.user_id AS "userId",
        u.email AS "userEmail",
        f.fact,
        f.type,
        f.confidence,
        f.status,
        f.source,
        f.created_at AS "createdAt",
        COALESCE(
          (
            SELECT t.business_id
            FROM threads t
            WHERE t.user_id::text = f.user_id
            ORDER BY t.created_at DESC
            LIMIT 1
          ),
          'ecommerce'
        ) AS "businessId"
      FROM long_memory_facts f
      LEFT JOIN users u ON u.id::text = f.user_id
    `;

    if (filterUserId) {
      query = sql`
        ${query}
        WHERE f.user_id = ${filterUserId} OR u.email = ${filterUserId}
      `;
    }

    query = sql`
      ${query}
      ORDER BY f.created_at DESC;
    `;

    const res = await drizzle.execute(query);
    const facts = res.rows || [];

    return NextResponse.json({ success: true, preferences: facts });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error('Error fetching preferences:', error);
    return NextResponse.json({ error: errMsg || 'Internal Server Error' }, { status: 500 });
  }
}

// POST /api/chat/preferences - 人工核准、驳回或删除画像事实
export async function POST(req: NextRequest) {
  try {
    const { preferenceId, action } = await req.json();

    if (!preferenceId || !action) {
      return NextResponse.json({ error: 'preferenceId and action are required' }, { status: 400 });
    }

    const drizzle = getDrizzle();
    if (!drizzle) {
      return NextResponse.json({ error: 'Database is offline' }, { status: 503 });
    }

    if (action === 'delete') {
      await drizzle.delete(longMemoryFacts).where(eq(longMemoryFacts.id, preferenceId));
      console.log(`[Admin Preference API] 🗑️ 成功物理删除偏好画像事实 ID: ${preferenceId}`);
      return NextResponse.json({ success: true, action: 'deleted' });
    }

    let nextStatus = 'rejected';
    if (action === 'approve') {
      nextStatus = 'approved';
    }

    await drizzle.update(longMemoryFacts).set({ status: nextStatus }).where(eq(longMemoryFacts.id, preferenceId));

    console.log(`[Admin Preference API] 🔒 画像事实核签完成：ID: ${preferenceId} ➔ 状态变更为: [${nextStatus}]`);

    return NextResponse.json({
      success: true,
      preferenceId,
      status: nextStatus,
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error('Error updating preference:', error);
    return NextResponse.json({ error: errMsg || 'Internal Server Error' }, { status: 500 });
  }
}
