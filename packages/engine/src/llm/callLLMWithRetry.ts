import { ChatOpenAI, OpenAIEmbeddings } from '@langchain/openai';
import { agentEventEmitter } from '../graph/eventEmitter';

// 🛡️ 物理自愈代理：在生产环境下，模型调用极易遭遇网络抖动或微服务瞬时延迟
// 本代理对系统允许使用的 'gemini-3.5-flash:latest' 模型进行 3次指数退避自动重试，提供核心决策链路高可用保障！
class ResilientLLM {
  private model: ChatOpenAI;
  private jobId?: string;

  constructor(model: ChatOpenAI, jobId?: string) {
    this.model = model;
    this.jobId = jobId;
  }

  async invoke(input: any, options?: any) {
    let attempts = 0;
    const maxAttempts = 3;
    let delay = 1000; // 初始退避 1 秒

    while (attempts < maxAttempts) {
      attempts++;
      try {
        if (attempts > 1 && this.jobId) {
          agentEventEmitter.emit(`${this.jobId}:status`, {
            status: 'executing',
            message: `⚠️ 大模型呼叫遭遇网络阻塞或短暂波动，执行引擎正在物理触发【自愈抗灾重试】：正在进行第 ${attempts} 次调用重试保障决策畅通...`,
          });
        }

        const response = await this.model.invoke(input, options);

        // 无感拦截并累加 Token 消耗
        try {
          let tokens = 0;
          if (response && (response as any).usage_metadata) {
            tokens = (response as any).usage_metadata.total_tokens || 0;
          } else if (response && (response as any).response_metadata) {
            const meta = (response as any).response_metadata;
            if (meta.tokenUsage) {
              tokens = meta.tokenUsage.totalTokens || 0;
            } else if (meta.usage) {
              tokens = meta.usage.total_tokens || 0;
            }
          }
          if (tokens > 0 && this.jobId) {
            agentEventEmitter.addTokens(this.jobId, tokens);
          }
        } catch (tokenErr) {
          console.warn('[Token Tracking Error]:', tokenErr);
        }

        return response;
      } catch (err: any) {
        console.warn(`[LLM Resilient Attempt ${attempts} Failed]:`, err.message || err);
        if (attempts >= maxAttempts) {
          throw err; // 达到最大尝试次数，最终向上抛出异常
        }
        // 指数退避重试延迟
        await new Promise((resolve) => setTimeout(resolve, delay));
        delay *= 2;
      }
    }
  }
}

export function getLLM(jobId?: string) {
  const llm = new ChatOpenAI({
    configuration: {
      baseURL: 'http://localhost:11211/api/openai/v1',
    },
    apiKey: 'dummy',
    modelName: 'gemini-3.5-flash:latest',
    temperature: 0,
  });

  // 返回鸭子类型的透明自愈代理，无缝平替原有的 ChatOpenAI，且 100% 只使用指定的物理模型
  return new ResilientLLM(llm, jobId) as any;
}

export function getEmbeddingModel() {
  return new OpenAIEmbeddings({
    configuration: {
      baseURL: 'http://localhost:11211/api/openai/v1',
    },
    apiKey: 'dummy',
    modelName: 'text-embedding-005:latest',
  });
}
