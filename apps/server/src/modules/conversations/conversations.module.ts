import { Module } from '@nestjs/common';
import { ConversationsController } from './conversations.controller';

@Module({
  controllers: [ConversationsController],
})
export class ConversationsModule {}
