import { describe, expect, test } from 'bun:test';
import { AgentStreamClient } from './agentStreamClient';

describe('AgentStreamClient Unit Tests', () => {
  test('Should construct AgentStreamClient with jobId', () => {
    const client = new AgentStreamClient('job_test_stream_001');
    expect(client).toBeDefined();
  });

  test('Should handle connect gracefully when EventSource is not present in Bun test runtime', () => {
    const client = new AgentStreamClient('job_test_stream_002');
    let errorHandled = false;

    const cleanup = client.connect({
      onError: (err) => {
        errorHandled = true;
      },
    });

    expect(typeof cleanup).toBe('function');
    cleanup();
    expect(errorHandled).toBe(true);
  });
});
