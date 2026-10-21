"""用量配额闸(2026-10-21,游客 10 次 + 商户积分池;spec .scratch/agent-usage-quota)。

闸序(accept_chat_turn 单点,chat/store 两通道共用):计数臂(Redis,Lua
全有或全无,拒绝不占名额)→ 商户池扣减(engine_py.credits,PG 单语句守卫)。

- 游客(guest-* 前缀自报身份,3005 面浏览器级稳定 ID)终身 AI_GUEST_QUOTA
  次(键无 TTL)+ 同 IP 每日 AI_GUEST_IP_DAILY 次;登录用户每日 AI_USER_DAILY
  次(UTC 日键);所有问询同扣所在 business_id 积分池(Q6:免费层=商户让利)。
- AI_QUOTA_GATE=0 整体关断(应急阀;密封测试套件缺省关,专项测试显式开)。
- Redis 计数臂故障 fail-open(对齐 rate_limit;池扣减是资金路径,PG 异常
  如实上抛,不静默放行)。
- 拒绝不落用户消息行、不派发 run_agent(D9);终局经 result 帧 quotaCode
  增量键承载机器语义 —— 尾只认 result 终局(stop_on),error 帧非终局会挂流,
  故 Q4 载体由 error 帧修订为 result 帧(修订记录见 spec)。
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass

from engine_py.credits import consume_credit
from engine_py.event_bus import get_client as get_redis

QUOTA_GUEST_LIMIT = "QUOTA_GUEST_LIMIT"
QUOTA_IP_LIMIT = "QUOTA_IP_LIMIT"
QUOTA_USER_DAILY = "QUOTA_USER_DAILY"
QUOTA_MERCHANT_EXHAUSTED = "QUOTA_MERCHANT_EXHAUSTED"

# 文案纪律(数据诚实律):不编造剩余额度,只陈述上限事实与出路
_GUEST_MSG = "您的免费问询次数已用完，注册或登录后可继续使用智能服务。"
_IP_MSG = "当前网络环境的免费试用额度已用完，请注册或登录后继续使用。"
_USER_DAILY_MSG = "您今日的问询次数已达上限，请明天再试。"
_EXHAUSTED_MSG = "当前商户的服务额度已用尽，请联系商户充值后继续使用。"

_ALLOWED = None  # 惰性单例(GateVerdict frozen dataclass)


@dataclass(frozen=True)
class GateVerdict:
    allowed: bool
    code: str = ""
    message: str = ""


def allowed() -> GateVerdict:
    global _ALLOWED
    if _ALLOWED is None:
        _ALLOWED = GateVerdict(True)
    return _ALLOWED


def gate_enabled() -> bool:
    return os.environ.get("AI_QUOTA_GATE", "1") != "0"


def is_guest(user_id: str) -> bool:
    """游客判定:guest-* 前缀(3005 面浏览器级 ID);web 面 JWT 身份恒非 guest。"""
    return bool(user_id) and user_id.startswith("guest-")


def _int_env(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


# 全有或全无:任一键超限全体回退(DECR 自愈,Lua 内原子无竞态),拒绝不占名额;
# ARGV = [limit_1..N, ttlMs_1..N],ttl 空串 = 终身键(游客额度)
_QUOTA_LUA = """
local over = 0
for i = 1, #KEYS do
  local v = redis.call('INCR', KEYS[i])
  if v > tonumber(ARGV[i]) then
    over = i
  end
end
if over > 0 then
  for i = 1, #KEYS do
    redis.call('DECR', KEYS[i])
  end
  return {0, over}
end
for i = 1, #KEYS do
  local ttl = ARGV[#KEYS + i]
  if ttl ~= '' then
    redis.call('PEXPIRE', KEYS[i], tonumber(ttl))
  end
end
return {1, 0}
"""


async def _check_counters(*, user_id: str, business_id: str, client_ip: str) -> GateVerdict:
    prefix = os.environ.get("AI_QUOTA_KEY_PREFIX", "quota")
    # UTC 日键:键名带日 + 48h TTL 双保险(跨日自然分桶,残留键自然消亡)
    day = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d")
    ttl_day = str(48 * 3600 * 1000)
    if is_guest(user_id):
        keys = [
            f"{prefix}:guest:{business_id}:{user_id}",
            f"{prefix}:ip:{business_id}:{client_ip}:{day}",
        ]
        limits = [str(_int_env("AI_GUEST_QUOTA", 10)), str(_int_env("AI_GUEST_IP_DAILY", 30))]
        ttls = ["", ttl_day]
    else:
        keys = [f"{prefix}:ud:{business_id}:{user_id}:{day}"]
        limits = [str(_int_env("AI_USER_DAILY", 5))]
        ttls = [ttl_day]
    verdict = await (await get_redis()).eval(_QUOTA_LUA, len(keys), *keys, *limits, *ttls)
    if not verdict[0]:
        over = int(verdict[1])
        if over == 1:
            if is_guest(user_id):
                return GateVerdict(False, QUOTA_GUEST_LIMIT, _GUEST_MSG)
            return GateVerdict(False, QUOTA_USER_DAILY, _USER_DAILY_MSG)
        return GateVerdict(False, QUOTA_IP_LIMIT, _IP_MSG)
    return allowed()


async def check_and_consume(
    *, user_id: str, business_id: str, client_ip: str, job_id: str
) -> GateVerdict:
    """回合起点闸:计数臂 → 池扣减。

    池尽拒时计数不回滚:池尽的商户所有问询恒拒,名额白烧无观测意义;池有
    额时的竞态窗口(peek 通过后他人耗尽)可忽略,扣减侧原子守卫兜底。
    """
    if not gate_enabled():
        return allowed()
    try:
        verdict = await _check_counters(user_id=user_id, business_id=business_id, client_ip=client_ip)
        if not verdict.allowed:
            return verdict
    except Exception as err:
        # fail-open:计数是反滥用臂;Redis 与事件主干同生共死,它挂时池扣减仍兜底
        print(f"[Quota] Redis 计数臂故障,fail-open 放行: {err}")
    if not await consume_credit(business_id, job_id=job_id):
        return GateVerdict(False, QUOTA_MERCHANT_EXHAUSTED, _EXHAUSTED_MSG)
    return allowed()
