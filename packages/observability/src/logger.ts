import pino from 'pino';

// In Next.js App Router / Serverless environments, dynamic runtime transports (like pino-pretty, thread-stream,
// and worker_threads) are not bundleable by Webpack and trigger 'MODULE_NOT_FOUND Cannot find module /vendor-chunks/lib/worker.js'
// or TypeErrors inside the thread-stream module during SSR page preredering.
// We avoid use of pino.transport() entirely in production or bundle/serverless builds, falling back to clean standard stdout logging.
const isBundledOrServerless =
  typeof window === 'undefined' && (process.env.NODE_ENV === 'production' || !!process.env.NEXT_RUNTIME);

export const logger = pino({
  level: process.env.LOG_LEVEL || 'info',
  ...(!isBundledOrServerless && typeof window === 'undefined' && process.env.NODE_ENV !== 'production'
    ? {
        transport: {
          target: 'pino-pretty',
          options: {
            colorize: true,
          },
        },
      }
    : {}),
});
