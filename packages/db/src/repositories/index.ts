import type { Message, Order } from '../schema';

export interface DBThread {
  id: string;
  userId: string;
  businessId: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface IUserRepository {
  findOrCreateUserByEmail(email: string): Promise<{ id: string; email: string }>;
}

export interface IThreadRepository {
  getUserThreads(userId: string): Promise<DBThread[]>;
  createThread(threadId: string, userId: string, businessId?: string): Promise<DBThread>;
  deleteThread(threadId: string): Promise<boolean>;
}

export interface IMessageRepository {
  getMessages(threadId: string): Promise<Message[]>;
  addMessage(message: Message): Promise<void>;
}

export interface IOrderRepository {
  getOrder(orderId: string): Promise<Order | null>;
}

export interface IDomainRepositories {
  user: IUserRepository;
  thread: IThreadRepository;
  message: IMessageRepository;
  order: IOrderRepository;
}
