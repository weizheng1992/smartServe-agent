/**
 * 高并发性能压测脚本 (Agent Platform Load Test Script)
 * 用法: bun scripts/load-test.ts --concurrency 10 --total 30 --url http://localhost:3000
 */

import { parseArgs } from "util";

const { values } = parseArgs({
  args: Bun.argv,
  options: {
    concurrency: { type: "string", default: "5" },
    total: { type: "string", default: "15" },
    url: { type: "string", default: "http://localhost:3000" },
  },
  strict: false,
  allowPositionals: true,
});

const CONCURRENCY = parseInt(values.concurrency || "5", 10);
const TOTAL_REQUESTS = parseInt(values.total || "15", 10);
const BASE_URL = (values.url || "http://localhost:3000").replace(/\/$/, "");

interface RequestMetric {
  id: number;
  jobId: string;
  status: "success" | "error";
  ttfbMs: number;
  totalDurationMs: number;
  error?: string;
}

const metrics: RequestMetric[] = [];
const sampleQueries = [
  "你好，请问你们客服营业时间是几点？",
  "帮我查询我的订单 ORD-98712 物流到哪了",
  "推荐一款适合春季透气跑鞋",
  "我想申请退款，订单号是 ORD-88888",
  "衣服码数不合适，怎么修改收货地址？",
];

async function runSingleRequest(id: number): Promise<RequestMetric> {
  const startTime = performance.now();
  const threadId = `load_test_thread_${id}_${Date.now()}`;
  const userId = `load_user_${id % 5}`;
  const query = sampleQueries[id % sampleQueries.length];

  try {
    // 1. 发起 POST /api/chat
    const postRes = await fetch(`${BASE_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: query, threadId, userId }),
    });

    const ttfbMs = Math.round(performance.now() - startTime);

    if (!postRes.ok) {
      const errText = await postRes.text();
      return {
        id,
        jobId: "unknown",
        status: "error",
        ttfbMs,
        totalDurationMs: ttfbMs,
        error: `HTTP ${postRes.status}: ${errText}`,
      };
    }

    const postData = (await postRes.json()) as { jobId?: string };
    const jobId = postData.jobId || `job_mock_${Date.now()}`;

    // 2. 模拟订阅 GET /api/chat/[jobId]/stream 获取 SSE 流
    const streamRes = await fetch(`${BASE_URL}/api/chat/${jobId}/stream`, {
      headers: { Accept: "text/event-stream" },
    });

    if (streamRes.body) {
      const reader = streamRes.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        if (
          chunk.includes("data: [DONE]") ||
          chunk.includes("status: finish")
        ) {
          break;
        }
      }
    }

    const totalDurationMs = Math.round(performance.now() - startTime);

    return {
      id,
      jobId,
      status: "success",
      ttfbMs,
      totalDurationMs,
    };
  } catch (err: unknown) {
    const totalDurationMs = Math.round(performance.now() - startTime);
    return {
      id,
      jobId: "failed",
      status: "error",
      ttfbMs: totalDurationMs,
      totalDurationMs,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

async function main() {
  console.log("=================================================");
  console.log("🚀 Agent 平台并发性能压测启动");
  console.log(`目标地址: ${BASE_URL}`);
  console.log(`并发线程: ${CONCURRENCY} | 总请求数: ${TOTAL_REQUESTS}`);
  console.log("=================================================\n");

  const startTime = performance.now();
  let currentIndex = 0;

  async function worker() {
    while (true) {
      const reqId = currentIndex++;
      if (reqId >= TOTAL_REQUESTS) break;
      const metric = await runSingleRequest(reqId);
      metrics.push(metric);
      const icon = metric.status === "success" ? "✅" : "❌";
      console.log(
        `[Req #${metric.id.toString().padStart(2, "0")}] ${icon} JobId: ${metric.jobId.padEnd(20)} | TTFB: ${metric.ttfbMs.toString().padStart(4)}ms | 总耗时: ${metric.totalDurationMs.toString().padStart(5)}ms`,
      );
    }
  }

  const workers = Array.from({ length: CONCURRENCY }, () => worker());
  await Promise.all(workers);

  const totalTimeMs = performance.now() - startTime;
  const successes = metrics.filter((m) => m.status === "success");
  const failures = metrics.filter((m) => m.status === "error");

  const durations = successes
    .map((m) => m.totalDurationMs)
    .sort((a, b) => a - b);
  const p50 = durations[Math.floor(durations.length * 0.5)] || 0;
  const p90 = durations[Math.floor(durations.length * 0.9)] || 0;
  const p99 = durations[Math.floor(durations.length * 0.99)] || 0;
  const avg = durations.length
    ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
    : 0;

  console.log("\n=================================================");
  console.log("📊 压测吞吐量与耗时统计报告 (Benchmark Summary)");
  console.log("=================================================");
  console.log(`⏱️ 总执行时间: ${(totalTimeMs / 1000).toFixed(2)}s`);
  console.log(
    `📈 完成请求数: ${metrics.length} (成功: ${successes.length}, 失败: ${failures.length})`,
  );
  console.log(
    `⚡ 吞吐量 (RPS): ${(metrics.length / (totalTimeMs / 1000)).toFixed(2)} req/s`,
  );
  console.log(`🎯 平均响应延迟: ${avg} ms`);
  console.log(
    `📊 P50 延迟: ${p50} ms | P90 延迟: ${p90} ms | P99 延迟: ${p99} ms`,
  );
  if (failures.length > 0) {
    console.log("\n⚠️ 失败请求错误例举:");
    failures
      .slice(0, 5)
      .forEach((f) => console.log(`  - Req #${f.id}: ${f.error}`));
  }
  console.log("=================================================\n");
}

main();
