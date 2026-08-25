import { type MiddlewareConsumer, Module, type NestModule } from '@nestjs/common';
import { APP_FILTER, APP_INTERCEPTOR } from '@nestjs/core';
import { HttpExceptionFilter } from './common/filters/http-exception.filter';
import { LoggingInterceptor } from './common/interceptors/logging.interceptor';
import { TenantMiddleware } from './common/tenant/tenant.middleware';
import { ApprovalsModule } from './modules/approvals/approvals.module';
import { BillingModule } from './modules/billing/billing.module';
import { ChatModule } from './modules/chat/chat.module';
import { ConversationsModule } from './modules/conversations/conversations.module';
import { EvalsModule } from './modules/evals/evals.module';
import { GatewayModule } from './modules/gateway/gateway.module';
import { GuardrailsModule } from './modules/guardrails/guardrails.module';
import { HealthModule } from './modules/health/health.module';
import { PersonasModule } from './modules/personas/personas.module';
import { RagModule } from './modules/rag/rag.module';
import { SkillsModule } from './modules/skills/skills.module';
import { MerchantSpiModule } from './modules/spi/merchant-spi.module';
import { SystemLogsModule } from './modules/system-logs/system-logs.module';
import { TenantModule } from './modules/tenant/tenant.module';

@Module({
  imports: [
    HealthModule,
    TenantModule,
    SkillsModule,
    ApprovalsModule,
    ChatModule,
    GatewayModule,
    ConversationsModule,
    MerchantSpiModule,
    RagModule,
    PersonasModule,
    GuardrailsModule,
    BillingModule,
    SystemLogsModule,
    EvalsModule,
  ],
  providers: [
    {
      provide: APP_FILTER,
      useClass: HttpExceptionFilter,
    },
    {
      provide: APP_INTERCEPTOR,
      useClass: LoggingInterceptor,
    },
  ],
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer) {
    consumer.apply(TenantMiddleware).forRoutes('*');
  }
}
