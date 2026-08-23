import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { logger } from 'observability';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule, {
    cors: {
      origin: true,
      credentials: true,
    },
    logger: ['error', 'warn', 'log'],
  });

  const port = process.env.PORT || 4000;
  await app.listen(port);
  logger.info(`🚀 NestJS Gateway Server is running on: http://localhost:${port}`);
}

bootstrap().catch((err) => {
  logger.error({ err }, 'Failed to start NestJS Gateway Server');
  process.exit(1);
});
