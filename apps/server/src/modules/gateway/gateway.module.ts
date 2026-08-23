import { Module } from '@nestjs/common';
import { ConversationGateway } from './conversation.gateway';

@Module({
  providers: [ConversationGateway],
  exports: [ConversationGateway],
})
export class GatewayModule {}
