"""作业中断原语(S2c,stream-reliability-push 04 号票)—— 用户主动停止在途回答。

三段语义:
- **登记表**:run_agent 派发时注册活跃作业、收口/异常时注销;网关取消路由
  (03 号票)调 ``request_cancel``。进程内实现是单实例假设(ADR-0007)下的
  最小形态,多实例部署须 Redis 化另立 ADR。
- **协作式检查点**:``run_graph_with_interruption`` 是 ``ainvoke`` 的检查点化
  等价物 —— astream 逐步消费全量状态快照,步间消费取消请求。命中即停:正在
  跑的节点自然完成(不撕 LLM 调用),后续节点不再执行;不取消时消费行为与
  ainvoke 等价,零行为漂移。
- **HITL 边界**:挂起(suspend_for_approval)是 run_agent 正常返回 —— 作业
  已注销,取消请求结构上打不中,``request_cancel`` 返回 False;本原语从设计
  上零接触 pending_approvals(审批面有自己的 cancel_execution 动作词,两不相干)。

终态语义归 run_agent:命中后 run 以 ``interrupted`` 收口(session_metrics
resolution_status 落独立值,与既有 resolved_auto/降级/子任务终态族区分),
部分态严禁冒充终稿。
"""

from __future__ import annotations

from typing import Any

# 进程级单例:事件循环单线程内 set 操作天然原子,无需加锁
_active_jobs: set[str] = set()
_cancel_requests: set[str] = set()
_job_owners: dict[str, str] = {}


def register_run(job_id: str, owner: str | None = None) -> None:
    """run_agent 派发时注册活跃作业;owner 记派发身份(``businessId:userId``,
    S2b 网关取消路由的属主闸数据源);空 job_id(本地无事件面)静默忽略。"""
    if job_id:
        _active_jobs.add(job_id)
        if owner is not None:
            _job_owners[job_id] = owner


def unregister_run(job_id: str) -> None:
    """run_agent 返回(正常/降级/异常)即注销;残留的待取消请求与属主一并清除。"""
    if job_id:
        _active_jobs.discard(job_id)
        _cancel_requests.discard(job_id)
        _job_owners.pop(job_id, None)


def peek_job_owner(job_id: str) -> str | None:
    """查活跃作业的派发身份;作业未知/已结束返回 None(网关据此 404)。"""
    return _job_owners.get(job_id)


def request_cancel(job_id: str) -> bool:
    """登记取消请求。空 job_id 或作业不在活跃登记表(已完成/挂起/未知)返回
    False —— 调用方(网关)据此映射 404/409 语义。重复调用幂等:效果收敛为一次。"""
    if not job_id or job_id not in _active_jobs:
        return False
    _cancel_requests.add(job_id)
    return True


def consume_cancel_request(job_id: str) -> bool:
    """检查点消费:命中即从待取消集清除并返回 True(同一请求只生效一次)。"""
    if job_id and job_id in _cancel_requests:
        _cancel_requests.discard(job_id)
        return True
    return False


async def run_graph_with_interruption(
    graph_app: Any,
    initial_state: dict,
    job_id: str,
) -> tuple[dict, bool]:
    """带检查点的图执行:返回 (终态或最后完成步快照, 是否被中断)。

    - 不取消:逐快照消费到底,最终快照与 ``ainvoke`` 返回等价,零行为漂移;
    - 取消:命中那一刻返回**最后完成步**的全量状态(部分产物)—— 正在执行的
      节点自然完成,后续节点永不运行;
    - 图异常照常向上传播(熔断/通用降级臂语义不变,由 run_agent 现有臂处理)。
    """
    result: dict = dict(initial_state)
    if consume_cancel_request(job_id):
        # 图启动前即取消:返回初始状态兜底(空 output,无节点产物可冒充)
        return result, True
    async for snapshot in graph_app.astream(initial_state, stream_mode="values"):
        result = snapshot
        if consume_cancel_request(job_id):
            return result, True
    return result, False
