/**
 * bun test 预加载钩子(密封化核心)
 *
 * 在任何测试模块求值之前启动 testcontainers 并注入 DATABASE_URL / REDIS_URL,
 * 保证 tools/cache.ts 这类"模块求值期即建连"的代码从第一刻起就指向容器,
 * 而不是本机 docker:up 的常驻服务。需要 Docker;未安装时会在此处尽早失败。
 */
import { initSealedEnv } from './helpers/sealedEnv';

await initSealedEnv();
