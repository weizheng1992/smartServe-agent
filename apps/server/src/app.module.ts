import {
  type MiddlewareConsumer,
  Module,
  type NestModule,
} from "@nestjs/common";
import { APP_FILTER, APP_INTERCEPTOR } from "@nestjs/core";
import { HttpExceptionFilter } from "./common/filters/http-exception.filter";
import { LoggingInterceptor } from "./common/interceptors/logging.interceptor";
import { TenantMiddleware } from "./common/tenant/tenant.middleware";
import { ChatModule } from "./modules/chat/chat.module";
import { ConversationsModule } from "./modules/conversations/conversations.module";
import { GatewayModule } from "./modules/gateway/gateway.module";
import { HealthModule } from "./modules/health/health.module";
import { MerchantSpiModule } from "./modules/spi/merchant-spi.module";
import { TenantModule } from "./modules/tenant/tenant.module";

@Module({
  imports: [
    HealthModule,
    TenantModule,
    ChatModule,
    GatewayModule,
    ConversationsModule,
    MerchantSpiModule,
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
    consumer.apply(TenantMiddleware).forRoutes("*");
  }
}
