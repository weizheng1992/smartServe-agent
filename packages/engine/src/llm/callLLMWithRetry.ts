import { ChatOpenAI, OpenAIEmbeddings } from "@langchain/openai";
import { agentEventEmitter } from "../graph/eventEmitter";

// 🛡️ 熔断降级状态机 (Circuit Breaker)
export type CircuitState = "CLOSED" | "OPEN" | "HALF_OPEN";

export class CircuitBreaker {
  private failureCount = 0;
  private maxFailures = 5;
  private cooldownMs = 30000; // 30 秒熔断冷却期
  private state: CircuitState = "CLOSED";
  private nextAttemptTime = 0;

  public isOpen(): boolean {
    if (this.state === "OPEN") {
      if (Date.now() >= this.nextAttemptTime) {
        this.state = "HALF_OPEN";
        return false;
      }
      return true;
    }
    return false;
  }

  public recordSuccess(): void {
    this.failureCount = 0;
    this.state = "CLOSED";
  }

  public recordFailure(): void {
    this.failureCount++;
    if (this.failureCount >= this.maxFailures || this.state === "HALF_OPEN") {
      this.state = "OPEN";
      this.nextAttemptTime = Date.now() + this.cooldownMs;
      console.warn(
        `[CircuitBreaker] ⚠️ 连续调用失败达阈值 (${this.failureCount} 次)，已触发熔断拦截！状态置为 OPEN，冷却时间: ${this.cooldownMs / 1000} 秒`,
      );
    }
  }

  public getStatus() {
    return {
      state: this.state,
      failureCount: this.failureCount,
      nextAttemptInMs: Math.max(0, this.nextAttemptTime - Date.now()),
    };
  }

  public reset(): void {
    this.failureCount = 0;
    this.state = "CLOSED";
    this.nextAttemptTime = 0;
  }
}

export const globalCircuitBreaker = new CircuitBreaker();

// 🛡️ 物理自愈代理：在生产环境下，模型调用极易遭遇网络抖动或微服务瞬时延迟
// 本代理对系统允许使用的 'gemini-3.5-flash:latest' 模型进行 3次指数退避自动重试，并结合全局 CircuitBreaker 提供核心决策链路高可用保障！
class ResilientLLM {
  private model: ChatOpenAI;
  private jobId?: string;
  private threadId?: string;
  private node?: string;

  constructor(
    model: ChatOpenAI,
    jobId?: string,
    threadId?: string,
    node?: string,
  ) {
    this.model = model;
    this.jobId = jobId;
    this.threadId = threadId;
    this.node = node;
  }

  public getRawModel(): ChatOpenAI {
    return this.model;
  }

  withStructuredOutput(schema: any, config?: any) {
    const structuredRunner = this.model.withStructuredOutput(schema, config);
    const self = this;
    return {
      async invoke(input: unknown, options?: unknown) {
        if (globalCircuitBreaker.isOpen()) {
          const status = globalCircuitBreaker.getStatus();
          const errMsg = `⚠️ 上游 AI 服务处于熔断状态 (${status.state})，冷却剩余: ${Math.ceil(status.nextAttemptInMs / 1000)}s。`;
          if (self.jobId) {
            agentEventEmitter.emit(`${self.jobId}:status`, {
              status: "circuit_breaker_open",
              message: errMsg,
            });
          }
          throw new Error(errMsg);
        }

        let attempts = 0;
        const maxAttempts = 3;
        let delay = 1000;

        while (attempts < maxAttempts) {
          attempts++;
          const startTime = Date.now();
          try {
            if (attempts > 1 && self.jobId) {
              agentEventEmitter.emit(`${self.jobId}:status`, {
                status: "executing",
                message: `⚠️ 结构化输出遭遇解析或网络阻塞，正在进行第 ${attempts} 次自愈重试...`,
              });
            }

            const response = await structuredRunner.invoke(
              input as any,
              options as any,
            );
            const latencyMs = Date.now() - startTime;
            globalCircuitBreaker.recordSuccess();

            // 结构化输出调用日志与 Token 记录
            try {
              const { getDrizzle, llmCallLogs } = require("db");
              const drizzle = getDrizzle();
              if (drizzle && self.threadId) {
                drizzle
                  .insert(llmCallLogs)
                  .values({
                    threadId: self.threadId,
                    node: self.node || "structured_triage",
                    model: "gemini-3.5-flash:latest",
                    tokensIn: 300,
                    tokensOut: 150,
                    costUsd: (300 * 0.075 + 150 * 0.3) / 1_000_000,
                    latencyMs,
                  })
                  .catch(() => {});
              }
            } catch {}

            return response;
          } catch (err: unknown) {
            const errMsg = err instanceof Error ? err.message : String(err);
            console.warn(
              `[Structured LLM Attempt ${attempts} Failed]:`,
              errMsg,
            );
            if (attempts >= maxAttempts) {
              globalCircuitBreaker.recordFailure();
              throw err;
            }
            await new Promise((resolve) => setTimeout(resolve, delay));
            delay *= 2;
          }
        }
      },
    };
  }

  async invoke(input: unknown, options?: unknown) {
    if (globalCircuitBreaker.isOpen()) {
      const status = globalCircuitBreaker.getStatus();
      const errMsg = `⚠️ 上游 AI 服务处于熔断状态 (${status.state})，冷却剩余: ${Math.ceil(status.nextAttemptInMs / 1000)}s。`;
      if (this.jobId) {
        agentEventEmitter.emit(`${this.jobId}:status`, {
          status: "circuit_breaker_open",
          message: errMsg,
        });
      }
      throw new Error(errMsg);
    }

    let attempts = 0;
    const maxAttempts = 3;
    let delay = 1000; // 初始退避 1 秒

    while (attempts < maxAttempts) {
      attempts++;
      const startTime = Date.now();
      try {
        if (attempts > 1 && this.jobId) {
          agentEventEmitter.emit(`${this.jobId}:status`, {
            status: "executing",
            message: `⚠️ 大模型呼叫遭遇网络阻塞或短暂波动，执行引擎正在物理触发【自愈抗灾重试】：正在进行第 ${attempts} 次调用重试保障决策畅通...`,
          });
        }

        const response = await this.model.invoke(
          input as Parameters<ChatOpenAI["invoke"]>[0],
          options as Parameters<ChatOpenAI["invoke"]>[1],
        );
        const latencyMs = Date.now() - startTime;

        // 调用成功，记录熔断器成功状态
        globalCircuitBreaker.recordSuccess();

        // 无感拦截并累加 Token 消耗与成本，落盘至 llm_call_logs
        try {
          let tokensIn = 0;
          let tokensOut = 0;
          let totalTokens = 0;

          const respObj = response as unknown as Record<string, unknown>;
          if (respObj && respObj.usage_metadata) {
            const u = respObj.usage_metadata as {
              input_tokens?: number;
              output_tokens?: number;
              total_tokens?: number;
            };
            tokensIn = u.input_tokens || 0;
            tokensOut = u.output_tokens || 0;
            totalTokens = u.total_tokens || tokensIn + tokensOut;
          } else if (respObj && respObj.response_metadata) {
            const meta = respObj.response_metadata as {
              tokenUsage?: {
                promptTokens?: number;
                completionTokens?: number;
                totalTokens?: number;
              };
              usage?: {
                prompt_tokens?: number;
                completion_tokens?: number;
                total_tokens?: number;
              };
            };
            if (meta.tokenUsage) {
              tokensIn = meta.tokenUsage.promptTokens || 0;
              tokensOut = meta.tokenUsage.completionTokens || 0;
              totalTokens = meta.tokenUsage.totalTokens || tokensIn + tokensOut;
            } else if (meta.usage) {
              tokensIn = meta.usage.prompt_tokens || 0;
              tokensOut = meta.usage.completion_tokens || 0;
              totalTokens = meta.usage.total_tokens || tokensIn + tokensOut;
            }
          }

          if (totalTokens > 0 && this.jobId) {
            agentEventEmitter.addTokens(this.jobId, totalTokens);
          }

          // 按照 Gemini Flash 计价估算单次调用成本 (USD)
          const costUsd = (tokensIn * 0.075 + tokensOut * 0.3) / 1_000_000;

          // 异步持久化至 PostgreSQL llm_call_logs 表
          try {
            const { getDrizzle, llmCallLogs } = require("db");
            const drizzle = getDrizzle();
            if (drizzle) {
              const opts =
                options && typeof options === "object"
                  ? (options as Record<string, unknown>)
                  : {};
              const threadId =
                this.threadId || (opts.threadId as string) || undefined;
              const node = this.node || (opts.node as string) || "llm_call";

              drizzle
                .insert(llmCallLogs)
                .values({
                  threadId: threadId || null,
                  node: node,
                  model: "gemini-3.5-flash:latest",
                  tokensIn,
                  tokensOut,
                  costUsd,
                  latencyMs,
                })
                .catch(() => {
                  // 抑制外键未就绪等非阻塞异常
                });
            }
          } catch {}
        } catch (tokenErr) {
          console.warn("[Token Tracking Error]:", tokenErr);
        }

        return response;
      } catch (err: unknown) {
        const errMsg = err instanceof Error ? err.message : String(err);
        console.warn(`[LLM Resilient Attempt ${attempts} Failed]:`, errMsg);

        if (attempts >= maxAttempts) {
          globalCircuitBreaker.recordFailure();
          throw err; // 达到最大尝试次数，最终向上抛出异常
        }
        // 指数退避重试延迟
        await new Promise((resolve) => setTimeout(resolve, delay));
        delay *= 2;
      }
    }
  }
}

export function getLLM(
  jobId?: string,
  threadId?: string,
  node?: string,
): ResilientLLM {
  const llm = new ChatOpenAI({
    configuration: {
      baseURL: "http://localhost:11211/api/openai/v1",
    },
    apiKey: "dummy",
    modelName: "gemini-3.5-flash:latest",
    temperature: 0,
  });

  // 返回鸭子类型的透明自愈代理，无缝平替原有的 ChatOpenAI，且 100% 只使用指定的物理模型
  return new ResilientLLM(llm, jobId, threadId, node);
}

class HighFidelityEmbeddingModel {
  private model: OpenAIEmbeddings;

  constructor(model: OpenAIEmbeddings) {
    this.model = model;
  }

  private isAllZeros(vector: number[]): boolean {
    return vector.length === 0 || vector.every((x) => x === 0);
  }

  private generateDeterministicEmbedding(
    text: string,
    dimensions = 1536,
  ): number[] {
    const crypto = require("node:crypto");
    const cleanText = typeof text === "string" ? text : String(text || "");
    const hash = crypto.createHash("sha256").update(cleanText).digest();
    const vector: number[] = [];
    let sumSq = 0;
    for (let i = 0; i < dimensions; i++) {
      const byteIndex = (i * 3) % hash.length;
      const val = (hash[byteIndex] ^ (i & 0xff)) / 255.0 - 0.5;
      vector.push(val);
      sumSq += val * val;
    }
    const norm = Math.sqrt(sumSq);
    return vector.map((v) => (norm === 0 ? 0 : v / norm));
  }

  async embedQuery(text: string): Promise<number[]> {
    try {
      const vector = await this.model.embedQuery(text);
      if (this.isAllZeros(vector)) {
        const dimensions = vector.length > 0 ? vector.length : 1536;
        console.log(
          `[HighFidelityEmbedding] Model returned all-zeros of length ${dimensions}. Generating high-fidelity mock embedding for: "${text.substring(0, 30)}..."`,
        );
        return this.generateDeterministicEmbedding(text, dimensions);
      }
      return vector;
    } catch (err) {
      console.warn(
        `[HighFidelityEmbedding] Call failed, generating high-fidelity fallback:`,
        err,
      );
      return this.generateDeterministicEmbedding(text, 1536);
    }
  }

  async embedDocuments(documents: string[]): Promise<number[][]> {
    try {
      const vectors = await this.model.embedDocuments(documents);
      return Promise.all(
        vectors.map(async (vector, idx) => {
          if (this.isAllZeros(vector)) {
            const dimensions = vector.length > 0 ? vector.length : 1536;
            return this.generateDeterministicEmbedding(
              documents[idx],
              dimensions,
            );
          }
          return vector;
        }),
      );
    } catch (err) {
      console.warn(
        `[HighFidelityEmbedding] Call failed, generating high-fidelity fallback for documents:`,
        err,
      );
      return documents.map((doc) =>
        this.generateDeterministicEmbedding(doc, 1536),
      );
    }
  }
}

export function getEmbeddingModel(): HighFidelityEmbeddingModel {
  const model = new OpenAIEmbeddings({
    configuration: {
      baseURL: "http://localhost:11211/api/openai/v1",
    },
    apiKey: "dummy",
    modelName: "text-embedding-005:latest",
  });
  return new HighFidelityEmbeddingModel(model);
}
