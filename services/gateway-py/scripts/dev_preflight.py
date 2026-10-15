"""dev 启动前置自检(2026-10-15 夜评台账 #3 收口)。

uvicorn --reload 只监视 gateway_py 树 —— engine_py 深链的语法错误/半成品
提交不会触发 reload,网关带旧代码或带病状态继续跑(09-17/09-18/09-20 三轮
「过期进程」事故);漏带 --env-file 也曾静默回退死端口。本闸在 uvicorn 之前
对两服务最深的公共入口做一次真导入:任何 ImportError/SyntaxError 响亮退出,
拒绝把网关拉起来。dev:server 脚本已串联本闸。
"""

from __future__ import annotations

import sys

CHECKS = ("engine_py.run_agent", "gateway_py.main")


def main() -> int:
    failures: list[tuple[str, BaseException]] = []
    for mod in CHECKS:
        try:
            __import__(mod)
            print(f"[Preflight] ✓ {mod}")
        except BaseException as err:  # 自检闸连 SystemExit 都要抓来报错
            failures.append((mod, err))
            print(f"[Preflight] ✗ {mod}: {err!r}")
    if failures:
        print(
            f"[Preflight] 🚨 {len(failures)} 个深模块导入失败,拒绝启动网关 —— "
            "先修复再起(过期/半成品进程是三轮巡检事故的直接根因)"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
