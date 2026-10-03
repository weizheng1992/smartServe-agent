"""LLM 调用韧性层 — TS 基线 callLLMWithRetry.ts 熔断/退避/超时三件套移植(wayfinder 003)。

- **熔断器全局单例**(TS 1:1,票内待定据此定案):连续失败达阈值(默认 5 次)
  或半开探测失败 → OPEN,冷却期(默认 30s)内调用直接拒绝;冷却过后转
  HALF_OPEN 放行探测,成功归零回 CLOSED。全局单例口径与 TS `globalCircuitBreaker`
  一致 —— 熔断的是"上游 LLM 服务可用性",与租户/模型无关。
- **指数退避**:最多 3 次尝试(默认),初始 1s 逐次翻倍;只有穷尽重试后的
  最终失败才计入熔断计数(TS 语义:中间重试成功即 record_success 清零)。
  终端失败(穷尽/总预算耗尽)若恰好触发跳闸 OPEN,改抛
  CircuitBreakerOpenError —— 跳闸即终端失败的真语义,节点穿透闸据此把
  job 级道歉降级接住(2026-09-30,详见 ``_trip_or_original``)。
- **超时**:每次尝试以 ``asyncio.wait_for`` 包裹(LLM_TIMEOUT_SECONDS,默认
  120s;≤0 视为关闭),超时视同失败参与退避与熔断。同步 invoke 无此层
  (引擎运行时全异步,同步路径仅供测试/脚本)。
- **挂点**::mod:`llm.chat` 的模型子类覆写公共 invoke/ainvoke —— 与遥测注入
  同一全覆盖挂点(with_structured_output 组合的子步骤同样经公共入口,
  2026-09-05 已证);triage 结构化 / planner / validator / finish / 画像审计
  全部调用点自动覆盖。
- **状态事件**:熔断拒绝与自愈重试经 Redis Streams 发布 ``${jobId}:status``
  (对齐 TS ``agentEventEmitter.emit(`${jobId}:status`)``);job_id 取自
  ``bind_llm_call_context`` 归因上下文,发布失败 print 留痕不阻断调用。
- **env**(逐调用读取,测试可 monkeypatch):``LLM_CIRCUIT_MAX_FAILURES``(5)、
  ``LLM_CIRCUIT_COOLDOWN_SECONDS``(30)、``LLM_RETRY_MAX_ATTEMPTS``(3)、
  ``LLM_RETRY_INITIAL_DELAY_MS``(1000)、``LLM_TIMEOUT_SECONDS``(120)。
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from ..event_bus import publish_agent_event
from .telemetry import current_llm_call_context

CircuitState = Literal["CLOSED", "OPEN", "HALF_OPEN"]


def _max_failures() -> int:
    return int(os.environ.get("LLM_CIRCUIT_MAX_FAILURES", "5"))


def _cooldown_ms() -> int:
    return int(os.environ.get("LLM_CIRCUIT_COOLDOWN_SECONDS", "30")) * 1000


def _max_attempts() -> int:
    return int(os.environ.get("LLM_RETRY_MAX_ATTEMPTS", "3"))


def _initial_delay_ms() -> int:
    return int(os.environ.get("LLM_RETRY_INITIAL_DELAY_MS", "1000"))


def _timeout_seconds() -> float | None:
    raw = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
    return raw if raw > 0 else None


def _total_deadline_seconds() -> float:
    """全部重试预算(2026-09-25 挂死修复):每尝试 120s × 3 次 + 退避 ≈ 6 分钟
    才降级,用户端表现为无限 loading(实弹:进程内连接悬死 + 供应商侧故障
    叠加)。总预算到期立即放弃剩余重试,整体失败让上层降级接管。"""
    raw = float(os.environ.get("LLM_TOTAL_DEADLINE_SECONDS", "180"))
    return raw if raw > 0 else None


def _now_ms() -> float:
    return time.time() * 1000


class CircuitBreaker:
    """连续失败熔断状态机(TS callLLMWithRetry.ts 1:1 移植)。

    ``now_ms`` 参数仅供测试注入合成时钟;缺省取墙钟。
    """

    def __init__(self) -> None:
        self.state: CircuitState = "CLOSED"
        self.failure_count = 0
        self.next_attempt_ms = 0.0

    def is_open(self, *, now_ms: float | None = None) -> bool:
        """OPEN 且仍在冷却 → True;冷却期满转 HALF_OPEN 放行一次探测。"""
        if self.state == "OPEN":
            now = _now_ms() if now_ms is None else now_ms
            if now >= self.next_attempt_ms:
                self.state = "HALF_OPEN"
                return False
            return True
        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self, *, now_ms: float | None = None) -> None:
        self.failure_count += 1
        # 半开探测失败 → 立即重回 OPEN 重置冷却(严于阈值判定,TS 同款)
        if self.state == "HALF_OPEN":
            self._open(now_ms=now_ms)
            print(
                f"[CircuitBreaker] ⚠️ 半开探测失败,熔断重回 OPEN,冷却时间: {_cooldown_ms() // 1000} 秒"
            )
        elif self.failure_count >= _max_failures():
            self._open(now_ms=now_ms)
            print(
                f"[CircuitBreaker] ⚠️ 连续调用失败达阈值({self.failure_count} 次),已触发熔断拦截!"
                f"状态置为 OPEN,冷却时间: {_cooldown_ms() // 1000} 秒"
            )

    def _open(self, *, now_ms: float | None) -> None:
        self.state = "OPEN"
        self.next_attempt_ms = (_now_ms() if now_ms is None else now_ms) + _cooldown_ms()

    def get_status(self, *, now_ms: float | None = None) -> dict[str, Any]:
        """键名保持 TS 基线 camelCase(state / failureCount / nextAttemptInMs)。"""
        now = _now_ms() if now_ms is None else now_ms
        return {
            "state": self.state,
            "failureCount": self.failure_count,
            "nextAttemptInMs": max(0, int(self.next_attempt_ms - now)),
        }

    def reset(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"
        self.next_attempt_ms = 0.0


# 全局单例:熔断对象是上游 LLM 服务可用性,跨节点共享(TS globalCircuitBreaker 1:1)
global_circuit_breaker = CircuitBreaker()


class CircuitBreakerOpenError(RuntimeError):
    """上游 LLM 熔断中,调用被拒绝;status 为熔断器状态快照。"""

    def __init__(self, status: dict[str, Any]) -> None:
        self.status = status
        super().__init__(
            f"⚠️ 上游 AI 服务处于熔断状态 ({status['state']}),"
            f"冷却剩余: {math.ceil(status['nextAttemptInMs'] / 1000)}s。"
        )


class ContentFilterError(RuntimeError):
    """供应商内容过滤确定性拒绝(bigmodel 400 contentFilter code 1301)。

    输入侧敏感词拦截对同一输入**必然同判**(2026-10-03 实弹:「比特币」类
    咨询三连重试全 400),重试纯属白烧退避;且不计熔断 —— 服务在线应答,
    被拒的是这一条输入,熔断器熔的是"上游可用性",语义不符。
    节点层(finish)据此给诚实拒答话术,严禁落「已由客服系统处理」谎报罐头。
    """


def _as_content_filter_error(err: Exception) -> ContentFilterError | None:
    """识别 bigmodel 输入侧内容过滤(400 contentFilter + code 1301)。

    窄匹配 1301 码:其他过滤形态(如输出侧 level/role 变体)不在确定性
    同判保证内,保持既有重试语义,防误伤。
    """
    text = str(err)
    if "contentFilter" in text and "1301" in text:
        return ContentFilterError(f"供应商内容过滤拦截输入(code 1301): {text[:300]}")
    return None


async def _sleep(delay_s: float) -> None:
    """退避等待(独立函数便于测试截获退避序列)。"""
    await asyncio.sleep(delay_s)


def _attempt_context_tag() -> str:
    """失败日志的归因前缀(observability §1.1:日志显式携带上下文元数据)。"""
    ctx = current_llm_call_context()
    if ctx is None:
        return ""
    return f" (jobId={ctx.job_id or '-'} threadId={ctx.thread_id or '-'})"


async def _emit_job_status(status: str, message: str) -> None:
    """向当前任务发布 LLM 韧性状态事件;无 job 归因或发布失败时静默降级。"""
    ctx = current_llm_call_context()
    job_id = ctx.job_id if ctx else None
    if not job_id:
        return
    try:
        await publish_agent_event(job_id, "status", {"status": status, "message": message})
    except Exception as err:
        print(f"[LLM Resilience] 状态事件发布失败(不阻断调用): {err}")


def _breaker_reject_status() -> dict[str, Any] | None:
    """熔断开启时返回状态快照(供构造拒绝错误),未开启返回 None。"""
    if global_circuit_breaker.is_open():
        return global_circuit_breaker.get_status()
    return None


def _trip_or_original(err: Exception) -> Exception:
    """终端失败(重试穷尽/总预算耗尽)的异常裁决:``record_failure`` 若恰好
    把熔断推至 OPEN,改抛 CircuitBreakerOpenError —— 跳闸即本轮终端失败的
    真语义,须经节点穿透闸(finish/planner/validator/consult_fast_path/
    llm_refine 前置上抛)接 run_agent 的 job 级道歉降级与
    resolution_status='llm_circuit_breaker' 落盘;否则当终端调用恰为该轮
    唯一 LLM 调用时(意图收敛后咨询类常如此),原始 ConnectionError 被节点
    generic except 吃成「已由客服系统处理」罐头,诚实降级永不触达
    (2026-09-30 熔断 E2E 实弹定位)。未跳闸(阈内失败)保持原始异常,
    节点级兜底照旧 —— 瞬时抖动的容错语义不变。"""
    if global_circuit_breaker.state == "OPEN":
        return CircuitBreakerOpenError(global_circuit_breaker.get_status())
    return err


async def resilient_ainvoke(attempt: Callable[[], Awaitable[Any]]) -> Any:
    """异步调用韧性包裹:熔断拒绝 → 指数退避重试 → 每次尝试超时中断。

    ``attempt`` 为零参工厂,每次重试构造全新协程(已 await 的协程不可重放)。
    """
    reject = _breaker_reject_status()
    if reject is not None:
        open_err = CircuitBreakerOpenError(reject)
        await _emit_job_status("circuit_breaker_open", open_err.args[0])
        raise open_err

    attempts = 0
    max_attempts = _max_attempts()
    delay_ms = _initial_delay_ms()
    deadline = _total_deadline_seconds()
    started = time.time()
    while True:
        attempts += 1
        remaining = deadline - (time.time() - started) if deadline else None
        if remaining is not None and remaining <= 1.0:
            # 总预算耗尽:继续重试只会让用户端 loading 更久(6 分钟级,实弹),
            # 立即按熔断口径失败,交由上层降级接管
            budget_err = TimeoutError(
                f"LLM 调用总预算({deadline:.0f}s)耗尽,放弃剩余重试(attempts={attempts})"
            )
            print(f"[LLM Resilience] {budget_err}{_attempt_context_tag()}")
            global_circuit_breaker.record_failure()
            terminal = _trip_or_original(budget_err)
            if terminal is not budget_err:
                await _emit_job_status("circuit_breaker_open", terminal.args[0])
                raise terminal from budget_err
            raise budget_err
        try:
            if attempts > 1:
                await _emit_job_status(
                    "executing",
                    f"⚠️ 大模型呼叫遭遇网络阻塞或短暂波动,执行引擎正在物理触发"
                    f"【自愈抗灾重试】:正在进行第 {attempts} 次调用保障决策畅通...",
                )
            per_attempt = _timeout_seconds()
            if remaining is not None and per_attempt is not None:
                per_attempt = min(per_attempt, remaining)
            elif remaining is not None:
                per_attempt = remaining
            result = await asyncio.wait_for(attempt(), timeout=per_attempt)
            global_circuit_breaker.record_success()  # 成功即清零连续失败计数(TS recordSuccess)
            return result
        except Exception as err:
            print(f"[LLM Resilience] 第 {attempts} 次尝试失败{_attempt_context_tag()}: {err}")
            filtered = _as_content_filter_error(err)
            if filtered is not None:
                # 确定性内容过滤:重试必然同判,快速失败;不计熔断(服务在线)
                await _emit_job_status("content_filter", filtered.args[0])
                raise filtered from err
            if attempts >= max_attempts:
                global_circuit_breaker.record_failure()
                terminal = _trip_or_original(err)
                if terminal is not err:
                    await _emit_job_status("circuit_breaker_open", terminal.args[0])
                    raise terminal from err
                raise
            await _sleep(delay_ms / 1000)
            delay_ms *= 2


def resilient_invoke(attempt: Callable[[], Any]) -> Any:
    """同步调用韧性包裹(熔断 + 退避,无超时层 — 仅供测试/脚本路径)。"""
    reject = _breaker_reject_status()
    if reject is not None:
        raise CircuitBreakerOpenError(reject)

    attempts = 0
    max_attempts = _max_attempts()
    delay_ms = _initial_delay_ms()
    while True:
        attempts += 1
        try:
            result = attempt()
            global_circuit_breaker.record_success()
            return result
        except Exception as err:
            print(f"[LLM Resilience] 第 {attempts} 次尝试失败{_attempt_context_tag()}: {err}")
            filtered = _as_content_filter_error(err)
            if filtered is not None:
                raise filtered from err
            if attempts >= max_attempts:
                global_circuit_breaker.record_failure()
                raise _trip_or_original(err) from err
            time.sleep(delay_ms / 1000)
            delay_ms *= 2
