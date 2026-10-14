"""作业中断原语契约(S2c,stream-reliability-push 04 号票)。

用户主动停止在途回答的引擎侧最小实现:
- 登记表语义:活跃作业可取消,已完成/挂起/未知作业取消请求打不中(HITL
  边界 —— 挂起作业的 run_agent 早已正常返回,不在活跃表,pending_approvals
  本原语零接触);
- 检查点语义:``run_graph_with_interruption`` 是 ainvoke 的检查点化等价物
  (astream 逐步消费全量状态,步间查闸)—— 不取消时行为不变;取消命中
  返回(最后完成步的全量状态, True),后续节点不再执行;协作式,不撕
  正在跑的 LLM 调用。

真 langgraph 段用内存 StateGraph(零 DB 零 LLM):节点 A 执行期间请求取消,
检查点在 A→B 边界命中,B 不得运行。
"""

from __future__ import annotations

from typing import TypedDict

import pytest

from engine_py.interruption import (
    consume_cancel_request,
    peek_job_owner,
    register_run,
    request_cancel,
    run_graph_with_interruption,
    unregister_run,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """登记表是进程级单例:每测前后清场,防用例间泄漏。"""
    from engine_py import interruption

    interruption._active_jobs.clear()
    interruption._cancel_requests.clear()
    interruption._job_owners.clear()
    yield
    interruption._active_jobs.clear()
    interruption._cancel_requests.clear()
    interruption._job_owners.clear()


class TestInterruptionRegistry:
    def test_request_cancel_unknown_job_returns_false(self):
        assert request_cancel("job_nobody") is False

    def test_register_then_request_then_consume_once(self):
        register_run("job_1")
        assert request_cancel("job_1") is True
        assert consume_cancel_request("job_1") is True
        assert consume_cancel_request("job_1") is False  # 幂等:待取消集消费即清

    def test_duplicate_requests_converge_to_single_cancel(self):
        register_run("job_1")
        assert request_cancel("job_1") is True
        assert request_cancel("job_1") is True  # 重复取消幂等:效果收敛为一次
        assert consume_cancel_request("job_1") is True
        assert consume_cancel_request("job_1") is False

    def test_unregister_job_is_not_cancellable(self):
        """已完成/挂起作业不可取消:run_agent 返回即注销,取消请求打不中。

        HITL 边界的引擎侧真相:挂起(suspend_for_approval)是 run_agent 正常
        return(waitingForApproval 子任务 + task_memory 落库),作业不在活跃表,
        本原语从结构上触碰不到 pending_approvals。
        """
        register_run("job_suspended")
        unregister_run("job_suspended")
        assert request_cancel("job_suspended") is False

    def test_owner_recorded_and_peekable(self):
        """S2b 属主闸:登记时记派发身份,peek 供网关取消路由校验。"""
        assert peek_job_owner("job_o") is None
        register_run("job_o", owner="aurora:CUST-1")
        assert peek_job_owner("job_o") == "aurora:CUST-1"
        unregister_run("job_o")
        assert peek_job_owner("job_o") is None, "注销必须连带清属主,防泄漏"

    def test_register_without_owner_is_cancellable_but_anonymous(self):
        """owner 缺省(None)兼容 S2c 形态:可取消性不变;网关 peek 到 None
        按 404「不存在或已结束」处理(生产路径 run_agent 恒记 owner,
        None 形态仅存于手工注册方)。"""
        register_run("job_anon")
        assert peek_job_owner("job_anon") is None
        assert request_cancel("job_anon") is True


class _RecordingFakeGraph:
    """astream 协议桩:on_yield 在产出第 i 块**之前**触发(建模「第 i 个节点
    执行期间」发生的事 —— 真图里节点先执行、执行完才产出快照)。"""

    def __init__(self, snapshots: list[dict], on_yield=None):
        self._snapshots = snapshots
        self._on_yield = on_yield
        self.consumed = 0

    async def astream(self, state, stream_mode=None):
        for i, snapshot in enumerate(self._snapshots, 1):
            if self._on_yield is not None:
                self._on_yield(i)
            self.consumed = i
            yield snapshot


class TestRunGraphWithInterruption:
    @pytest.mark.asyncio
    async def test_no_cancel_returns_final_snapshot_ainvoke_equivalent(self):
        snaps = [{"output": "s1"}, {"output": "s2"}, {"output": "final"}]
        graph = _RecordingFakeGraph(snaps)
        result, interrupted = await run_graph_with_interruption(graph, {"output": "init"}, "job_x")
        assert interrupted is False
        assert result == {"output": "final"}
        assert graph.consumed == 3

    @pytest.mark.asyncio
    async def test_cancel_mid_stream_stops_before_next_node(self):
        register_run("job_mid")  # 镜像 run_agent 接线:图跑起来前作业必在活跃表
        snaps = [{"step": 1}, {"step": 2}, {"step": 3}]

        def cancel_during_second_node(n):
            if n == 2:
                assert request_cancel("job_mid") is True  # 用户在第 2 节点执行期间点停

        graph = _RecordingFakeGraph(snaps, on_yield=cancel_during_second_node)
        result, interrupted = await run_graph_with_interruption(graph, {"step": 0}, "job_mid")
        assert interrupted is True
        assert result == {"step": 2}  # 最后完成步的全量状态
        assert graph.consumed == 2  # 第 3 节点从未执行

    @pytest.mark.asyncio
    async def test_cancel_before_graph_start_skips_stream(self):
        register_run("job_early")
        assert request_cancel("job_early") is True
        graph = _RecordingFakeGraph([{"step": 1}])
        result, interrupted = await run_graph_with_interruption(graph, {"step": 0}, "job_early")
        assert interrupted is True
        assert result == {"step": 0}  # 初始状态兜底,不冒充任何节点产物
        assert graph.consumed == 0  # astream 从未被拉起

    @pytest.mark.asyncio
    async def test_real_langgraph_cancel_fires_at_step_boundary(self):
        """真 langgraph 图:A 节点执行期间用户点停止 → A→B 边界检查点命中,
        B 节点不得运行(协作式中断,当前节点自然完成)。"""
        from langgraph.graph import END, START, StateGraph

        ran: list[str] = []

        class _State(TypedDict, total=False):
            steps: list[str]

        def node_a(state: _State) -> dict:
            ran.append("a")
            request_cancel("job_rg")  # 用户在 A 执行中点了停止
            return {"steps": ["a"]}

        def node_b(state: _State) -> dict:
            ran.append("b")
            return {"steps": [*state.get("steps", []), "b"]}

        graph = StateGraph(_State)
        graph.add_node("a", node_a)
        graph.add_node("b", node_b)
        graph.add_edge(START, "a")
        graph.add_edge("a", "b")
        graph.add_edge("b", END)
        app = graph.compile()

        register_run("job_rg")  # 镜像 run_agent 接线
        result, interrupted = await run_graph_with_interruption(app, {"steps": []}, "job_rg")
        assert ran == ["a"], f"B 节点必须被检查点拦截: ran={ran!r}"
        assert interrupted is True
        assert result.get("steps") == ["a"]
