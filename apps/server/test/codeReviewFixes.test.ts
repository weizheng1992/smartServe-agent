import { describe, expect, it, mock } from 'bun:test';
import { ConversationRepository } from 'db';
import { ApprovalGatekeeper, agentEventEmitter } from 'engine';
import { ApprovalsService } from '../src/modules/approvals/approvals.service';
import { ChatService } from '../src/modules/chat/chat.service';
import { SkillsController } from '../src/modules/skills/skills.controller';
import { SkillsService } from '../src/modules/skills/skills.service';

describe('🛡️ Code Review Fixes Validation Suite', () => {
  describe('1. ConversationRepository Tenant Isolation', () => {
    it('should strictly isolate timeline queries by tenant businessId', async () => {
      const threadId = `test_thread_isolation_${Date.now()}`;

      // Insert message for nike
      await ConversationRepository.appendMessage({
        threadId,
        businessId: 'nike',
        userId: 'CUST-NIKE-01',
        role: 'user',
        content: 'I want to query my Nike order',
      });

      // Query with matching tenant
      const matching = await ConversationRepository.getConversationTimeline(threadId, 'nike');
      expect(matching).not.toBeNull();
      expect(matching?.thread.businessId).toBe('nike');
      expect(matching?.messages.length).toBe(1);

      // Query with mismatched tenant should return null
      const mismatched = await ConversationRepository.getConversationTimeline(threadId, 'adidas');
      expect(mismatched).toBeNull();
    });
  });

  describe('2. Approvals SQL Push-down Filtering', () => {
    it('should support tenant filter pushed down to listPendingApprovals', async () => {
      const service = new ApprovalsService();

      const approvalsNike = await service.listApprovals('nike');
      expect(Array.isArray(approvalsNike)).toBe(true);

      for (const app of approvalsNike) {
        if (app.businessId) {
          expect(app.businessId).toBe('nike');
        }
      }

      const approvalsAll = await service.listApprovals('all');
      expect(Array.isArray(approvalsAll)).toBe(true);
    });
  });

  describe('3. SSE Cross-Connection Event Replay via Last-Event-ID', () => {
    it('should replay missed events across separate pipeSSE connections', async () => {
      const service = new ChatService();
      const jobId = `job_sse_reconnect_${Date.now()}`;
      const conn1Chunks: string[] = [];
      const conn2Chunks: string[] = [];

      let conn1Close: (() => void) | null = null;
      let conn2Close: (() => void) | null = null;

      const mockRes1: any = {
        setHeader: mock(() => {}),
        flushHeaders: mock(() => {}),
        write: mock((c: string) => conn1Chunks.push(c)),
        end: mock(() => {}),
        on: (event: string, cb: () => void) => {
          if (event === 'close') conn1Close = cb;
        },
      };

      // Connection 1 connects
      service.pipeSSE(jobId, mockRes1);

      // Emit 3 events on conn1
      agentEventEmitter.emit('thought', { jobId, step: 'Step 1' });
      agentEventEmitter.emit('thought', { jobId, step: 'Step 2' });
      agentEventEmitter.emit('thought', { jobId, step: 'Step 3' });

      expect(conn1Chunks.length).toBe(3);
      expect(conn1Chunks[0]).toContain('id: 1');
      expect(conn1Chunks[1]).toContain('id: 2');
      expect(conn1Chunks[2]).toContain('id: 3');

      // Conn 1 disconnects
      if (conn1Close) (conn1Close as () => void)();

      // Emit 4th event while client is disconnected
      agentEventEmitter.emit('thought', {
        jobId,
        step: 'Step 4 while disconnected',
      });

      // Connection 2 reconnects with Last-Event-ID: 2 (client missed events 3 & 4)
      const mockRes2: any = {
        setHeader: mock(() => {}),
        flushHeaders: mock(() => {}),
        write: mock((c: string) => conn2Chunks.push(c)),
        end: mock(() => {}),
        on: (event: string, cb: () => void) => {
          if (event === 'close') conn2Close = cb;
        },
      };

      service.pipeSSE(jobId, mockRes2, '2');

      // Verify that events with id > 2 (i.e. id 3 and id 4) were replayed immediately on reconnect
      expect(conn2Chunks.length).toBeGreaterThanOrEqual(2);
      expect(conn2Chunks.some((c) => c.includes('id: 3'))).toBe(true);
      expect(conn2Chunks.some((c) => c.includes('id: 4'))).toBe(true);

      if (conn2Close) (conn2Close as () => void)();
    });
  });

  describe('4. SkillsController RESTful Config Endpoints', () => {
    it('should expose /api/skills/config GET and PUT routes', async () => {
      const skillsService = new SkillsService();
      const controller = new SkillsController(skillsService);

      const tenantContext = { tenantId: 'aurora' };

      // Test GET /api/skills/config
      const getConfigRes = await controller.getSkillsConfig(tenantContext as any);
      expect(getConfigRes.success).toBe(true);
      expect(getConfigRes.tenantId).toBe('aurora');
      expect(Array.isArray(getConfigRes.skills)).toBe(true);

      // Test PUT /api/skills/config
      const putConfigRes = await controller.updateSkillsConfig(tenantContext as any, {
        skillId: 'order_refund',
        approvalThresholdAmount: 250,
      });
      expect(putConfigRes.success).toBe(true);
      expect(putConfigRes.tenantId).toBe('aurora');
      expect(putConfigRes.skillId).toBe('order_refund');
    });
  });
});
