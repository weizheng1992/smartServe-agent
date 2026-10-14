import { describe, expect, test } from 'bun:test';
import { interruptGeneration, markInterrupted } from './interruptGeneration';

function fetchStub(status: number, calls: string[] = []) {
  return (input: string, init?: { method: string }) => {
    calls.push(`${init?.method ?? 'GET'} ${input}`);
    return Promise.resolve({ ok: status >= 200 && status < 300, status });
  };
}

describe('interruptGeneration', () => {
  test('200 受理:ok true,userId/businessId 走 query,jobId 编码', async () => {
    const calls: string[] = [];
    const outcome = await interruptGeneration(
      { jobId: 'job a/b', userId: 'CUST-1', businessId: 'aurora' },
      fetchStub(200, calls),
    );
    expect(outcome).toEqual({ ok: true, status: 200 });
    expect(calls).toEqual(['POST /api/chat/job%20a%2Fb/cancel?userId=CUST-1&businessId=aurora']);
  });

  test('404 作业已结束:ok false(调用方等 result 帧收尾,不报错)', async () => {
    const outcome = await interruptGeneration({ jobId: 'job_1', userId: 'CUST-1' }, fetchStub(404));
    expect(outcome).toEqual({ ok: false, status: 404 });
  });

  test('网络层失败:ok false status 0(不抛异常炸调用方)', async () => {
    const outcome = await interruptGeneration({ jobId: 'j', userId: 'u' }, () =>
      Promise.reject(new Error('network down')),
    );
    expect(outcome).toEqual({ ok: false, status: 0 });
  });

  test('无 businessId 时 query 不带该键(与网关缺省语义一致)', async () => {
    const calls: string[] = [];
    await interruptGeneration({ jobId: 'j', userId: 'u' }, fetchStub(200, calls));
    expect(calls[0]).toBe('POST /api/chat/j/cancel?userId=u');
  });
});

describe('markInterrupted', () => {
  type Msg = {
    jobId?: string;
    isLoading?: boolean;
    role: string;
    content: string;
    interrupted?: boolean;
  };
  const loader: Msg = { jobId: 'job_1', isLoading: true, role: 'assistant', content: '' };

  test('目标加载气泡就地转「已停止」态:部分输出保留 + interrupted 标记', () => {
    const msgs: Msg[] = [loader, { jobId: 'other', isLoading: true, role: 'assistant', content: 'x' }];
    const next = markInterrupted(msgs, 'job_1', '');
    expect(next[0]).toEqual({
      jobId: 'job_1',
      isLoading: false,
      role: 'assistant',
      content: '',
      interrupted: true,
    });
    expect(next[1]).toEqual({ jobId: 'other', isLoading: true, role: 'assistant', content: 'x' });
  });

  test('部分输出(引擎部分态)原样保留,严禁丢弃或改写', () => {
    const next = markInterrupted<Msg>([{ ...loader }], 'job_1', '已生成的半段文字');
    expect(next[0].content).toBe('已生成的半段文字');
    expect(next[0].interrupted).toBe(true);
  });

  test('非加载行(历史消息)不受波及', () => {
    const history: Msg = { role: 'assistant', content: '历史回复', jobId: 'job_old' };
    const next = markInterrupted([history], 'job_old', '');
    expect(next[0]).toEqual(history);
  });
});
