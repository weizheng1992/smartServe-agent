# testing —— 测试分层、命令与判绿纪律

## 分层金字塔(自下而上)

1. **pytest 契约**(`services/gateway-py/tests/`):事实标准。全量 `bun run test:eval`;单文件 `cd services/gateway-py && uv run pytest tests/test_http_routes_contract.py`。SSE 测试必须 live_server;analytics 43 条由 test_analytics_routes.py(93 例)专册。
2. **vitest**(各 app 内,与被测文件同目录):`bun run test`;单文件必须 `bun run test -- run <file>`(bunx vitest 走 Bun 运行时会炸 esbuild)。
3. **Playwright e2e**(`apps/merchant/e2e/` 六册等):`bun run test:e2e`;复用运行中的 3005 + 4000;跨册身份注入 addInitScript **参数字面量**(引用 Node 闭包常量 = 浏览器 ReferenceError 或静默身份错位);宿主 env 须 `AI_QUOTA_GATE=0`。
4. **promptfoo 评测**:`bun run test:prompt`(Classify)/ `:planner` / `:pin`(钉基线)/ `:compare`(对比门禁);judge 事实基线律——answerQuality 看不见 DB/语料,expectedRules 不写全真值就把真实值当编造。

## 判绿纪律

- 播种回路必须断言行数(docker exec 无 -i 静默吞 heredoc,exit 0 零落库 = 假绿)。
- 引擎脚本测试必须 drain 事件流,否则落盘蒸发。
- SQL 修复终审须 asyncpg 层参数绑定复现(psql 复现不了绑定差异)。

## 基建扰动签名(报错 ≠ 代码缺陷)

- testcontainers:InvalidPasswordError user "u" / 起容器阻塞 = 基建扰动;免 DB 子集秒绿即清白;并行会话全量跑放大扰动。
- pytest Py3.14 退出阶段挂死:测试跑完卡 _Py_Finalize;日志直写文件,见 N passed 后 kill 即得完整结果。
- 商户表加列须同步各测试文件本地 DDL 副本(共享容器字母序冻结形状)。
- 手拉网关必须 `--env-file`(漏 AI_BASE_URL 静默回退死端口,症状像管线 bug)。
- 并行会话期 uv run 可能卡死:ruff/pytest 改用 `services/.venv/bin/` 直呼。
- MetricHead hash 编码器隐式联网回退:有网机器绿 / 沙箱挂,用 faulthandler_timeout 定位。

## 环境闸

- `AI_QUOTA_GATE=0`(游客终身 10 次用量闸,缺省关;开着跑 e2e 会撞配额慢性翻红)。
- `ENGINE_SCHEDULER_ENABLED=0`(并行会话/夜评独立端口时关周期任务)。
- 夜评固定独立端口 NIGHTLY_BASE_URL=4001(scheduler 关),严禁占用 4000。
