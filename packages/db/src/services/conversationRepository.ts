import { getPgPool } from "../client";

export interface ListConversationsFilter {
  businessId: string;
  status?: string;
  tag?: string;
  searchKeyword?: string;
  limit?: number;
  offset?: number;
}

export interface ConversationSummary {
  threadId: string;
  businessId: string;
  userId?: string;
  status: string;
  assignedOperatorId?: string;
  unreadCount: number;
  tags: string[];
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  lastMessageSnippet?: string;
  lastMessageRole?: string;
  lastMessageTime?: string;
}

export interface AppendMessagePayload {
  id?: string;
  threadId: string;
  businessId: string;
  userId?: string;
  role: "user" | "assistant" | "system" | "operator";
  content: string;
  thoughtSteps?: Array<{ step: string; status: string }>;
  toolCalls?: Array<{ name: string; args: any; result?: any }>;
  cards?: Array<{ cardType: string; payload: any }>;
  operatorInfo?: { operatorId: string; operatorName: string };
  timestamp?: string;
}

export class ConversationRepository {
  /**
   * 按租户查询聚合会话列表 (支持状态过滤、意图标签检索与全文模糊搜索)
   */
  public static async listConversations(
    filter: ListConversationsFilter,
  ): Promise<{ items: ConversationSummary[]; total: number }> {
    const pool = getPgPool();
    const cleanBizId = (filter.businessId || "").toLowerCase().trim();
    const limit = Math.max(1, Math.min(100, filter.limit ?? 20));
    const offset = Math.max(0, filter.offset ?? 0);

    const conditions: string[] = [];
    const params: any[] = [];
    let paramIndex = 1;

    if (cleanBizId && cleanBizId !== "all") {
      conditions.push(`t.business_id = $${paramIndex}`);
      params.push(cleanBizId);
      paramIndex++;
    }

    if (filter.status && filter.status !== "all") {
      conditions.push(`t.status = $${paramIndex}`);
      params.push(filter.status);
      paramIndex++;
    }

    if (filter.tag) {
      conditions.push(`t.tags @> $${paramIndex}::jsonb`);
      params.push(JSON.stringify([filter.tag]));
      paramIndex++;
    }

    if (filter.searchKeyword && filter.searchKeyword.trim() !== "") {
      const keyword = `%${filter.searchKeyword.trim()}%`;
      conditions.push(`(
        t.id ILIKE $${paramIndex} OR
        EXISTS (
          SELECT 1 FROM messages m
          WHERE m.thread_id = t.id AND m.content ILIKE $${paramIndex}
        )
      )`);
      params.push(keyword);
      paramIndex++;
    }

    const whereClause =
      conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

    // 1. 获取总记录数
    const countQuery = `SELECT COUNT(*) as count FROM threads t ${whereClause}`;
    const countRes = await pool.query(countQuery, params);
    const total = Number.parseInt(countRes.rows[0]?.count || "0", 10);

    // 2. 分页拉取列表及最新一条消息
    const listQuery = `
      SELECT
        t.id as thread_id,
        t.business_id,
        t.user_id,
        t.status,
        t.assigned_operator_id,
        COALESCE(t.unread_count, 0) as unread_count,
        COALESCE(t.tags, '[]'::jsonb) as tags,
        COALESCE(t.metadata, '{}'::jsonb) as metadata,
        t.created_at,
        t.updated_at,
        m.content as last_msg_content,
        m.role as last_msg_role,
        m.timestamp as last_msg_time
      FROM threads t
      LEFT JOIN LATERAL (
        SELECT content, role, timestamp
        FROM messages
        WHERE thread_id = t.id
        ORDER BY created_at DESC, timestamp DESC
        LIMIT 1
      ) m ON true
      ${whereClause}
      ORDER BY t.updated_at DESC
      LIMIT $${paramIndex} OFFSET $${paramIndex + 1}
    `;

    const listParams = [...params, limit, offset];
    const res = await pool.query(listQuery, listParams);

    const items: ConversationSummary[] = res.rows.map((r) => ({
      threadId: r.thread_id,
      businessId: r.business_id,
      userId: r.user_id,
      status: r.status || "active",
      assignedOperatorId: r.assigned_operator_id,
      unreadCount: r.unread_count,
      tags: Array.isArray(r.tags) ? r.tags : [],
      metadata: r.metadata || {},
      createdAt: r.created_at
        ? new Date(r.created_at).toISOString()
        : new Date().toISOString(),
      updatedAt: r.updated_at
        ? new Date(r.updated_at).toISOString()
        : new Date().toISOString(),
      lastMessageSnippet: r.last_msg_content
        ? r.last_msg_content.length > 80
          ? r.last_msg_content.slice(0, 80) + "..."
          : r.last_msg_content
        : undefined,
      lastMessageRole: r.last_msg_role,
      lastMessageTime: r.last_msg_time,
    }));

    return { items, total };
  }

  /**
   * 获取单会话完整消息时序与上下文 (强制租户物理隔离与智能自愈)
   */
  public static async getConversationTimeline(
    threadId: string,
    businessId?: string,
  ) {
    const pool = getPgPool();
    const cleanThreadId = threadId.trim();
    const cleanBizId = (businessId || "").toLowerCase().trim();

    // 1. 查询会话基础信息
    const threadQuery = "SELECT * FROM threads WHERE id = $1";
    const threadRes = await pool.query(threadQuery, [cleanThreadId]);
    if (!threadRes.rows[0]) return null;

    const thread = threadRes.rows[0];
    let actualBizId = (thread.business_id || "ecommerce").toLowerCase();

    // 🛡️ 多租户身份校验与自愈补全：
    // 如果当前会话处于默认 'ecommerce' 或者 threadId 明显归属当前商户，且客户端以指定商户（如 aurora）查询，自动自愈升级会话归属
    if (cleanBizId && cleanBizId !== "all") {
      if (actualBizId === cleanBizId) {
        // 完全匹配
      } else if (
        actualBizId === "ecommerce" ||
        cleanThreadId.includes(cleanBizId)
      ) {
        await pool.query("UPDATE threads SET business_id = $2 WHERE id = $1", [
          cleanThreadId,
          cleanBizId,
        ]);
        actualBizId = cleanBizId;
        thread.business_id = cleanBizId;
      } else {
        // 严格物理隔离：不同专营商户之间禁止越权访问
        return null;
      }
    }

    // 2. 查询消息列表 (使用绑定的 business_id 进行物理隔离过滤)
    const msgQuery = `
      SELECT id, role, content, thought_steps, tool_calls, cards, operator_info, timestamp, created_at
      FROM messages
      WHERE thread_id = $1 AND (business_id = $2 OR business_id = 'ecommerce' OR business_id IS NULL)
      ORDER BY created_at ASC, timestamp ASC
    `;
    const msgRes = await pool.query(msgQuery, [cleanThreadId, actualBizId]);

    return {
      thread: {
        threadId: thread.id,
        businessId: thread.business_id,
        userId: thread.user_id,
        status: thread.status,
        assignedOperatorId: thread.assigned_operator_id,
        unreadCount: thread.unread_count || 0,
        tags: thread.tags || [],
        metadata: thread.metadata || {},
        createdAt: thread.created_at,
        updatedAt: thread.updated_at,
      },
      messages: msgRes.rows.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        thoughtSteps: m.thought_steps || undefined,
        toolCalls: m.tool_calls || undefined,
        cards: m.cards || undefined,
        operatorInfo: m.operator_info || undefined,
        timestamp: m.timestamp,
        createdAt: m.created_at,
      })),
    };
  }

  /**
   * 更新会话状态机 (如转人工接管、归档等)
   */
  public static async updateConversationStatus(params: {
    threadId: string;
    businessId: string;
    status: string;
    assignedOperatorId?: string | null;
    tags?: string[];
    metadata?: Record<string, unknown>;
  }) {
    const pool = getPgPool();
    const cleanBizId = params.businessId.toLowerCase().trim();
    const cleanThreadId = params.threadId.trim();

    // Ensure thread row exists before updating
    await pool.query(
      `INSERT INTO threads (id, business_id, status, created_at, updated_at)
       VALUES ($1, $2, $3, NOW(), NOW())
       ON CONFLICT (id) DO UPDATE SET business_id = EXCLUDED.business_id`,
      [cleanThreadId, cleanBizId, params.status],
    );

    const updates: string[] = ["status = $3", "updated_at = NOW()"];
    const queryParams: any[] = [cleanThreadId, cleanBizId, params.status];
    let pIdx = 4;

    if (params.assignedOperatorId !== undefined) {
      updates.push(`assigned_operator_id = $${pIdx}`);
      queryParams.push(params.assignedOperatorId);
      pIdx++;
    }

    if (params.tags !== undefined) {
      updates.push(`tags = $${pIdx}::jsonb`);
      queryParams.push(JSON.stringify(params.tags));
      pIdx++;
    }

    if (params.metadata !== undefined) {
      updates.push(
        `metadata = COALESCE(metadata, '{}'::jsonb) || $${pIdx}::jsonb`,
      );
      queryParams.push(JSON.stringify(params.metadata));
      pIdx++;
    }

    const query = `
      UPDATE threads
      SET ${updates.join(", ")}
      WHERE id = $1 AND business_id = $2
      RETURNING *
    `;

    const res = await pool.query(query, queryParams);
    return res.rows[0] || null;
  }

  /**
   * 写入一条新消息并更新会话 updatedAt
   */
  public static async appendMessage(payload: AppendMessagePayload) {
    const pool = getPgPool();
    const msgId =
      payload.id ||
      `msg_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
    const timestamp = payload.timestamp || new Date().toISOString();
    const cleanBizId = payload.businessId.toLowerCase().trim();
    const cleanUserId = payload.userId?.trim() || null;

    // 1. 保证 thread 存在并关联用户
    await pool.query(
      `INSERT INTO threads (id, business_id, user_id, status, created_at, updated_at)
       VALUES ($1, $2, $3, 'active', NOW(), NOW())
       ON CONFLICT (id) DO UPDATE SET
         updated_at = NOW(),
         business_id = EXCLUDED.business_id,
         user_id = COALESCE(EXCLUDED.user_id, threads.user_id)`,
      [payload.threadId, cleanBizId, cleanUserId],
    );

    // 2. 插入消息
    const msgRes = await pool.query(
      `INSERT INTO messages (
        id, thread_id, business_id, role, content, thought_steps, tool_calls, cards, operator_info, timestamp, created_at
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
      RETURNING *`,
      [
        msgId,
        payload.threadId,
        cleanBizId,
        payload.role,
        payload.content,
        payload.thoughtSteps ? JSON.stringify(payload.thoughtSteps) : null,
        payload.toolCalls ? JSON.stringify(payload.toolCalls) : null,
        payload.cards ? JSON.stringify(payload.cards) : null,
        payload.operatorInfo ? JSON.stringify(payload.operatorInfo) : null,
        timestamp,
      ],
    );

    return msgRes.rows[0];
  }
}
