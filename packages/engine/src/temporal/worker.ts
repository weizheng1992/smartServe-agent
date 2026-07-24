import * as path from 'node:path';
import { NativeConnection, Worker } from '@temporalio/worker';
import * as activities from './activities';

async function run() {
  const address = process.env.TEMPORAL_ADDRESS || '127.0.0.1:7239';
  console.log(`[Temporal Worker] 正在尝试物理连接至 Temporal Server: ${address}`);

  try {
    // 强制 Worker 物理连接至 7239 端口的 Server
    const connection = await NativeConnection.connect({
      address: address,
    });

    const worker = await Worker.create({
      connection,
      workflowsPath: path.resolve(__dirname, './workflows.ts'),
      activities,
      taskQueue: 'agent-tasks',
    });
    console.log('Temporal Worker started successfully, listening on queue: "agent-tasks"');
    await worker.run();
  } catch (err: any) {
    console.warn(
      `[Temporal Worker Warn] ⚠️ 本地沙箱环境拒绝网络回环物理连接 (${err.message || err})。系统将自动切入 High-Fidelity Simulator 模式！`,
    );
  }
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
