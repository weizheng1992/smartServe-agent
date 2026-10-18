"""租户边界与员工身份 — 网关身份闸唯一深模块(架构审查 #1 收口,2026-10-04)。

此前同一「身份 → 租户边界 → 裁决」不变量以 7 种手写形态散布五个路由文件
(四批安全修复 c7b26cd / 91348c9 / 29beb83 / 1317d43 全属装配遗漏类),收敛为
一个 module:路由声明,不再各自装配。

Interface(调用方须知的一切):

- ``StaffIdentity``:已解析员工身份(email + staff ORM 行)。JWT 只带 email,
  租户由 DB 行带出(与登录/发货同一身份模型),严禁采信客户端自报租户。
- ``resolve_staff(authorization) -> StaffIdentity | None``:无 Authorization 头
  或有效 token 但非在职员工 → None(顾客语义);坏/登出 token → 401
  (require_claims,沿用 {"detail"} 缺省形状)。
- ``require_staff(authorization) -> StaffIdentity``:必须在职员工;无/坏/登出
  token 401、非员工/停用 403(HTTPException {"detail"} 形,契约钉死)。
- ``bound_tenant(staff, tenant_param) -> str``:员工可见租户边界 —— 参数缺省取
  员工真租户;显式他租与 ``all`` 聚合一律 GateError 403(架构不变量 #1)。
  等值比较大小写不敏感(全仓 business_id 一律 lower().strip() 口径)。
- ``ensure_tenant_registered(business_id) -> None``:商户注册表闸,fail-closed
  (403 未注册/停用、503 注册表不可达)。raise 型 —— 不再返回 gate-or-None
  逼调用方抄 ``if gate is not None: return gate`` 咒语(该咒语曾复制 6 份,
  漏抄即闸静默失效)。
- ``same_tenant(a, b) -> bool``:大小写不敏感租户等值谓词。钉死 ``{"detail"}``
  呈现形状的调用方(管理台审批面,契约钉文案)继续自行 raise HTTPException,
  但比较必须走本谓词 —— 呈现按面适配,机制单点。
- ``staff_scope`` / ``staff_identity``:FastAPI Depends 依赖,在处理器体**之前**
  落闸 —— 身份/租户拒绝天然不被处理器内兜底 except 吞成 500。
- ``require_tenant()``:contextvar 租户闸(x-tenant-id 头系;与员工身份闸平行
  的另一身份模型, analytics/管理面自报头语义)。
- ``GateError``:业务闸拒绝类型(HTTPException 子类),由 main.py 全局 handler
  渲染为平台统一信封 ``{"success": false, error|message}``(server-gateway §1.4);
  ``field`` 供个别面钉死的历史键名(message)覆写。**两形规则**(契约钉死,
  见 tests/test_http_routes_contract.py TestMerchantTenantGate):身份/租户闸
  (require_staff / bound_tenant)走 HTTPException {"detail"} 形;业务闸
  (注册表 ensure_tenant_registered / 对象归属 / 权限点)走 GateError success 形。

铁律:GateError 只能在兜底 ``except Exception`` 作用域**之外** raise(依赖注入
闸天然满足;处理器体内 raise 须先放行 ``except HTTPException``),否则闸被吞
成 500 —— 正是本模块要消灭的事故类。
"""

from __future__ import annotations

from typing import NamedTuple, TypedDict

from fastapi import Header, HTTPException, Query
from sqlalchemy import select, text

from .tenant_context import get_tenant_context

# 函数体内 import(沿用既有惯例规避 routers ↔ auth 循环依赖):
# require_claims / get_session / StaffMember 在使用点引入。


class GateError(HTTPException):
    """身份/租户闸拒绝。全局 handler(main.py)渲染 {"success": false, <field>}。"""

    def __init__(self, status_code: int, message: str, *, field: str = "error"):
        super().__init__(status_code=status_code, detail=message)
        self.field = field


class StaffIdentity(NamedTuple):
    email: str
    staff: object  # engine_py.db.StaffMember(ORM 行;避免顶层 import 环)


class TenantScope(NamedTuple):
    """员工身份 + 其可见租户(staff_scope 依赖的产出)。"""

    identity: StaffIdentity
    tenant: str

    @property
    def staff(self):
        return self.identity.staff

    @property
    def email(self) -> str:
        return self.identity.email


def same_tenant(a: str | None, b: str | None) -> bool:
    """大小写不敏感租户等值(全仓 business_id lower().strip() 口径的谓词单点)。"""
    if not a or not b:
        return False
    return str(a).strip().lower() == str(b).strip().lower()


async def resolve_staff(authorization: str | None) -> StaffIdentity | None:
    """Bearer JWT → 在职员工;无头/非员工/停用 → None(顾客语义)。

    坏/登出 token 照 require_claims 语义 401 直穿(与既有各面一致)。
    """
    if not (authorization or "").strip():
        return None
    from .routers.auth import require_claims  # 本模块在 gateway_py 顶层,.auth 须显式走 routers 包

    claims = await require_claims(authorization)
    email = str(claims.get("email") or "")
    staff = await _enabled_staff_by_email(email)
    if staff is None:
        return None
    return StaffIdentity(email=email, staff=staff)


async def require_staff(authorization: str | None) -> StaffIdentity:
    """必须在职员工:无/坏/登出 token 401(require_claims 同语义),非员工/停用 403。

    身份/租户闸的拒绝呈现走 {"detail"} 形(HTTPException)—— 该形状由契约钉死
    (tests/test_http_routes_contract.py TestMerchantTenantGate:「身份/租户闸走
    HTTPException 形,业务错才走 success 形」)。
    """
    from .routers.auth import require_claims

    claims = await require_claims(authorization)
    staff = await _enabled_staff_by_email(str(claims.get("email") or ""))
    if staff is None:
        raise HTTPException(status_code=403, detail="非商户员工或已停用")
    return StaffIdentity(email=str(claims.get("email") or ""), staff=staff)


async def optional_staff(authorization: str | None) -> StaffIdentity | None:
    """可选身份闸(管理台审批面/chat 未读清零用):无 Authorization 头 → None
    (顾客语义);有效 token 但非在职员工(平台注册顾客账号)→ None 亦按顾客
    处理;坏/登出 token 401 直穿({"detail"} 形,同 require_staff)。
    """
    if not (authorization or "").strip():
        return None
    from .routers.auth import require_claims

    claims = await require_claims(authorization)
    email = str(claims.get("email") or "")
    staff = await _enabled_staff_by_email(email)
    if staff is None:
        return None
    return StaffIdentity(email=email, staff=staff)


async def _enabled_staff_by_email(email: str):
    """JWT email → 在职员工行;查无或停用 → None(身份解析的共享查询)。"""
    from engine_py.db import StaffMember, get_session

    if not email:
        return None
    async with get_session() as session:
        staff = (
            await session.execute(select(StaffMember).where(StaffMember.email == email))
        ).scalars().first()
    if staff is None or staff.status != "enabled":
        return None
    return staff


def bound_tenant(staff, tenant_param: str | None) -> str:
    """员工可见租户边界:缺省取员工真租户,他租/all 聚合 403(不变量 #1)。

    呈现走 {"detail"} 形(身份/租户闸契约,同 require_staff)。
    """
    if not tenant_param or same_tenant(tenant_param, staff.business_id):
        return staff.business_id
    raise HTTPException(status_code=403, detail=f"跨租户访问被拒绝(员工租户 {staff.business_id})")


async def staff_identity(authorization: str | None = Header(None)) -> StaffIdentity:
    """Depends 闸:处理器体之前完成 401/403 裁决(不需租户参数的路由用)。"""
    return await require_staff(authorization)


async def staff_scope(
    authorization: str | None = Header(None),
    tenantId: str | None = Query(None),
) -> TenantScope:
    """Depends 闸:员工身份 + 租户边界一次落定(商户管理面标准入口)。"""
    identity = await require_staff(authorization)
    return TenantScope(identity=identity, tenant=bound_tenant(identity.staff, tenantId))


class StaffContext(TypedDict):
    """analytics 面请求上下文(2026-10-18 闸族收口,键集契约物):此前
    analytics._ctx 返回未声明 dict,engine 侧 ``session_ctx.get("role", …)`` 的
    lenient 缺省把键漂移变成「静默按 finance_owner 放行」—— 键集自此有类型。"""

    business_id: str
    role: str
    staff: str
    staff_id: object
    display: str
    perms: list[str]


_staff_seeded_tenants: set[str] = set()


async def staff_context(
    authorization: str | None = Header(None),
) -> StaffContext:
    """Depends 闸(analytics 面标准入口,2026-10-18 闸族收口):租户上下文 +
    员工身份 + 角色/权限点一次装配。原 analytics._ctx 手写平行实现上收于此
    (_seeded_tenants 幂等缓存随迁);require_tenant_context/_PermissionError
    双胞胎随之退役,无租户上下文 403 统一 {"detail"} 形(两形规则 detail 半边,
    原 {statusCode,message} 信封零契约用例钉过)。perms 暂随装配(与旧 _ctx
    同开销);只读路由免付 perms 的两档化留作后续。"""
    tc = get_tenant_context()
    if not (tc and tc.get("tenantId")):
        raise HTTPException(403, "Forbidden: tenant context required (x-tenant-id header)")
    from engine_py.analytics import rbac

    from .routers.auth import require_claims

    claims = await require_claims(authorization)
    business_id = tc["tenantId"]
    if business_id not in _staff_seeded_tenants:
        await rbac.ensure_defaults(business_id)
        _staff_seeded_tenants.add(business_id)
    staff = await rbac.find_staff(business_id, str(claims.get("email") or ""))
    if staff is None or staff.status != "enabled":
        raise HTTPException(status_code=403, detail="非商户员工或已停用")
    return {
        "business_id": business_id,
        "role": staff.role,
        "staff": staff.email,
        "staff_id": staff.id,
        "display": staff.display_name,
        "perms": await rbac.perms_for_role(business_id, staff.role),
    }


PLATFORM_ADMIN_ROLE = "platform_admin"  # 角色名沿用 spi/gatekeeper 既有白名单字面量


async def operator_scope(authorization: str | None, tenant_param: str | None) -> tuple[str, StaffIdentity]:
    """坐席/管控双面闸(2026-10-18):员工 JWT 必需;platform_admin 跨租户
    (显式租户参数缺省 'all' 上帝视角),普通员工**钉本租户**——自报租户头不再
    采信(provenance:租户来源从「头自报」变「身份推导」,admin conversations
    四端点的 'ecommerce' 兜底链随之消灭)。返回 (tenant_id, identity)。"""
    identity = await require_staff(authorization)
    if str(identity.staff.role or "") == PLATFORM_ADMIN_ROLE:
        return str(tenant_param or "all").strip().lower(), identity
    return str(identity.staff.business_id or "").strip().lower(), identity


async def require_platform_admin(
    authorization: str | None = Header(None),
) -> StaffIdentity:
    """Depends 闸:平台运营者(2026-10-18 平台面零鉴权收口)。

    SaaS 管控台(tenant CRUD/overview/billing/skills/rag/evals/logs/guardrails/
    personas 等跨租户上帝视角)须持 role='platform_admin' 员工 JWT(business_id
    ='all' 的平台账号,rbac.ensure_platform_admin 启动期种子)—— 此前自报
    x-tenant-id/x-role 即可匿名读写,「刻意上帝视角」与「忘了装闸」在签名上
    零差别,审计只能逐条考古。401/403 {"detail"} 形(同 require_staff)。"""
    identity = await require_staff(authorization)
    if str(identity.staff.role or "") != PLATFORM_ADMIN_ROLE:
        raise HTTPException(status_code=403, detail="需要平台运营者角色(platform_admin)")
    return identity


async def ensure_tenant_registered(business_id: str | None) -> None:
    """商户注册表闸(raise 型):403 未注册/停用、503 注册表不可达(fail-closed)。

    仅约束商户服务路径;平台主站 /api/chat 通路不受限(内置租户不走商户入驻)。
    "all" 为聚合视图参数,非单租户扮演,直接放行。
    """
    from engine_py.db import get_session

    clean = (business_id or "").strip().lower()
    if clean == "all":
        return
    try:
        async with get_session() as session:
            row = (
                await session.execute(
                    text("SELECT status FROM tenants WHERE LOWER(business_id) = :bid LIMIT 1"),
                    {"bid": clean},
                )
            ).first()
    except Exception as err:
        print(f"[TenantGate] tenants 注册表查询失败(fail-closed 拒绝请求): {err}")
        raise GateError(503, "租户注册表暂不可用，请稍后重试") from err
    if row is None or str(row[0] or "").lower() != "active":
        print(f"[TenantGate] 拒绝未注册/已停用商户租户: {business_id!r}")
        raise GateError(403, f"商户 '{business_id}' 未入驻或已停用，请联系平台完成商户注册")


def require_tenant() -> dict:
    """contextvar 租户闸(x-tenant-id 头系):无租户上下文(且非 admin)→ 403。

    沿用 {"detail"} 缺省形状(管理面契约),不走 GateError 信封。
    """
    ctx = get_tenant_context()
    if ctx and ctx.get("tenantId"):
        return ctx
    raise HTTPException(403, "Forbidden: tenant context required (x-tenant-id header)")


async def has_perm(business_id: str, role: str, perm: str) -> bool:
    """按钮权限点判定(rbac.perms_for_role 的 fail-closed 包装):判定失败按
    无权限处理并响亮留痕,调用方(realtime socket 动作闸 / chat 未读清零)
    不必各写一份 try/except。live_desk HTTP 面刻意仍直调 rbac(失败要 500 响亮)。"""
    from engine_py.analytics import rbac

    try:
        return perm in await rbac.perms_for_role(business_id, role)
    except Exception as err:
        print(f"[TenantScope] perm 判定失败(按无权限处理): {err}")
        return False
