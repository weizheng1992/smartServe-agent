"""跨语言/跨面闭集 parity(2026-10-26 夜评晨审挂账 + 2026-10-28 终审扩容)。

- 承运商译名:gateway ``merchant_domain._CARRIER_LABELS`` ↔ ``apps/merchant/
  src/lib/logistics.ts CARRIER_LABELS`` ↔ ``apps/merchant-admin/src/lib/
  format.ts CARRIER_OPTIONS``(实存三份拷贝,format.ts 注释自认「四处同步」)
- 卡片动作:engine 全量 ``"action": "<name>"`` 发射字面量 + onboarding
  ``_ALLOWED_ACTIONS`` 词表字面量 ↔ ``packages/types/src/card-actions.ts
  CARD_ACTIONS``(目录自称单一事实源,但未覆盖引擎侧)
- 种子图:``merchant_seed.py``/``catalog.py`` 的 ``/api/seed-images/*`` 引用 ↔
  ``gateway_py/seed_images/`` 目录(手抄双表,2026-10-28 终审补钉)

TS 侧解析刻意走正则(格式稳定);解析失败必须响亮(非空断言),严禁空集
静默绿;块内注释先剥除防注释词凭空入白名单。升级为生成物流的路线见
tools-registry §1.5。
"""

from __future__ import annotations

import re
from pathlib import Path

from gateway_py.merchant_domain import _CARRIER_LABELS

REPO_ROOT = Path(__file__).resolve().parents[3]

# 组件级例外:trigger_upload 需组件内 fileInputRef,两侧均刻意不入模块级
# 策略表(apps/merchant/src/components/chat/FloatingChatWidget.tsx 同型注释;
# web ChatArea 同)—— 目录若未来收编该动作须同步改此处与两组件。
_COMPONENT_LEVEL_ACTIONS = {"trigger_upload"}


def _strip_ts_comments(src: str) -> str:
    """剥 TS 块注释与行注释(终审:注释里的单引号小写词会凭空进白名单)。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return "\n".join(re.sub(r"//.*$", "", line) for line in src.splitlines())


def test_carrier_labels_parity_three_copies():
    """承运商译名三表全等(gateway / merchant logistics / merchant-admin format)。"""
    py_map = dict(_CARRIER_LABELS)

    logistics = _strip_ts_comments((REPO_ROOT / "apps/merchant/src/lib/logistics.ts").read_text(encoding="utf-8"))
    block = re.search(r"CARRIER_LABELS[^=]*=\s*\{(.*?)\}", logistics, re.DOTALL)
    assert block, "logistics.ts CARRIER_LABELS 块解析失败(文件格式变了?)"
    merchant_map = dict(re.findall(r"([A-Za-z]+)\s*:\s*'([^']+)'", block.group(1)))
    assert merchant_map, "merchant 承运商表解析为空 —— 解析器与文件格式漂移,须人工核"
    assert merchant_map == py_map, f"gateway↔merchant 承运商译名漂移: {py_map} vs {merchant_map}"

    fmt = _strip_ts_comments((REPO_ROOT / "apps/merchant-admin/src/lib/format.ts").read_text(encoding="utf-8"))
    opts = re.search(r"CARRIER_OPTIONS\s*=\s*\[(.*?)\]\s*as const", fmt, re.DOTALL)
    assert opts, "format.ts CARRIER_OPTIONS 数组解析失败(文件格式变了?)"
    admin_map = dict(re.findall(r"code:\s*'([A-Za-z]+)'(?:[^}]*?)label:\s*'([^']+)'", opts.group(1)))
    assert admin_map, "merchant-admin 承运商选项解析为空 —— 解析器与文件格式漂移,须人工核"
    assert admin_map == py_map, f"gateway↔merchant-admin 承运商译名漂移: {py_map} vs {admin_map}"


def test_engine_card_actions_within_ts_catalog():
    """engine 发射的卡片动作 ⊆ TS 目录 ∪ 组件级例外;新动作未登记即红。

    发射面扫描两形态(终审补):dict 字面量 ``"action": "x"`` + 词表集合字面量
    (onboarding._ALLOWED_ACTIONS —— 集合内动作名同样是引擎可发射闭集)。
    """
    src = _strip_ts_comments((REPO_ROOT / "packages/types/src/card-actions.ts").read_text(encoding="utf-8"))
    block = re.search(r"export const CARD_ACTIONS = \[(.*?)\] as const", src, re.DOTALL)
    assert block, "card-actions.ts CARD_ACTIONS 数组解析失败(文件格式变了?)"
    catalog = set(re.findall(r"'([a-z_]+)'", block.group(1)))
    assert len(catalog) >= 12 and "send_message" in catalog, (
        f"TS 动作目录解析异常(仅 {sorted(catalog)})—— 解析器与文件格式漂移,须人工核"
    )

    emitted: set[str] = set()
    engine_root = REPO_ROOT / "services/engine-py/src/engine_py"
    for py in engine_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        emitted |= set(re.findall(r'"action"\s*:\s*"([a-z_]+)"', text))
        wl = re.search(r"_ALLOWED_ACTIONS\s*=\s*\{(.*?)\}", text, re.DOTALL)
        if wl:
            emitted |= set(re.findall(r"'([a-z_]+)'", wl.group(1)))
    assert emitted, "engine 动作发射面扫描为空 —— 扫描正则与发射形态漂移,须人工核"

    unknown = emitted - catalog - _COMPONENT_LEVEL_ACTIONS
    assert not unknown, (
        f"engine 发射了目录外卡片动作: {sorted(unknown)} —— 请在 packages/types "
        "card-actions.ts CARD_ACTIONS 登记(组件级例外须在此册显式扩员)"
    )
    # 反向钉(终审):例外清单只许收编真实在发射的动作 —— 动作退役/目录收编后
    # 例外条目若不清理,这里红灯提示清单已陈旧
    stale = _COMPONENT_LEVEL_ACTIONS - emitted
    assert not stale, f"组件级例外清单陈旧(下列动作 engine 已不再发射): {sorted(stale)}"


def test_seed_image_refs_parity():
    """种子图引用 ↔ 静态目录双向全等:引用指空=生产碎图,文件无引用=死重。"""
    refs: set[str] = set()
    for py_name in ("merchant_seed.py",):
        refs |= set(
            re.findall(
                r"/api/seed-images/([^\"'\s]+)",
                (REPO_ROOT / "services/gateway-py/src/gateway_py" / py_name).read_text(encoding="utf-8"),
            )
        )
    catalog_py = (REPO_ROOT / "services/engine-py/src/engine_py/tools_registry/mall/catalog.py").read_text(encoding="utf-8")
    refs |= set(re.findall(r"/api/seed-images/([^\"'\s]+)", catalog_py))

    files = {p.name for p in (REPO_ROOT / "services/gateway-py/src/gateway_py/seed_images").iterdir() if p.is_file()}
    assert refs and files, "种子图引用或目录扫描为空 —— 文件挪位/前缀改名,须人工核"
    assert refs <= files, f"引用了不存在的种子图(生产碎图): {sorted(refs - files)}"
    assert files <= refs, f"目录中存在零引用的死图(死重): {sorted(files - refs)}"
