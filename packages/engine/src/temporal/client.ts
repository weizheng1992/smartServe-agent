import { Client, Connection } from '@temporalio/client';

let clientPromise: Promise<Client> | null = null;
let useMock = true; // 默认采用模拟模式
let hasChecked = false;

// 动态检测当前环境是否可以使用真实的 Temporal Server
export function isUsingMockTemporal(): boolean {
  // 如果尚未进行物理探针检测，或者是在后台静默轮询，这里返回当前检测出的状态
  return useMock;
}

export async function getTemporalClient(): Promise<Client> {
  if (clientPromise) return clientPromise;

  clientPromise = (async () => {
    const address = process.env.TEMPORAL_ADDRESS || '127.0.0.1:7239';
    console.log(`[Temporal Client] 正在尝试物理连接至真实 Temporal Server: ${address}...`);

    try {
      // 尝试进行一次超快速的物理连接探针（1秒超时）
      const connection = await Connection.connect({
        address: address,
        connectTimeout: 1500,
      });

      console.log('[Temporal Client] ✅ 真实物理 Temporal 引擎连接成功！');
      useMock = false;
      hasChecked = true;

      return new Client({
        connection,
        namespace: process.env.TEMPORAL_NAMESPACE || 'default',
      });
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.warn(`[Temporal Client] ⚠️ 无法物理连接至 Temporal Server (${errMsg})。`);
      console.warn(
        '[Temporal Client] 🚀 系统已自动无缝切换至: High-Fidelity Client-side simulator (LangGraph 本地直跑) 模式！',
      );
      useMock = true;
      hasChecked = true;

      // 如果连接失败，返回一个假的 Client 占位符，避免上层抛出空指针，具体运行会走 isUsingMockTemporal 分流
      return {} as Client;
    }
  })();

  return clientPromise;
}

// 物理模块加载时，自触发一次异步探针检测，尽早确定是使用真实物理 Temporal 还是本地模拟器
getTemporalClient().catch(() => {});
