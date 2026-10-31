# REVIEW-CHECKLIST.md

变更审查清单。逐项核对;任何一项不过 = 打回。详细依据见 `AGENTS.md` §2-§3 与 `.claude/rules/` 对应册。

## 正确性与边界

1. 租户边界:每条新增数据库查询与工具执行是否携带 `tenantId` / `businessId`?跨库读取是否走 `_merchant_reader_engine` 而非直连?
2. 数据诚实:是否存在编造兜底值(`|| 899` 类假价、unsplash 假图、编造承运商缺省、编造库存)?缺值是否诚实呈现?
3. 契约冻结:是否改动 TS 冻结基线路由 / SSE 线格式 / socket.io 事件?新增端点是否同批补 pytest 契约测试?
4. SQL 守卫:新增数据访问是否经 `sql_guard.py` AST 审计与闭集模板?是否存在绕闸直连?
5. HITL:敏感动作(超阈值退款、地址修改)是否挂起 + 发件箱同事务?恢复路径是否走 Fast-Path / outbox worker?
6. 事务边界:`get_session` 的 commit 是否在 async-with 块内(上下文外 commit = 静默回滚)?

## 架构与依赖

7. UI:是否只用 workspace 包 `ui` + Tailwind?是否引入重型组件框架或手写原生控件?Radix Select 空值两律是否遵守?
8. 单点模块:商户面 HTTP 是否收口 `api.ts`?购物车读写是否走 `storeCart.ts`?裸 fetch 是否只出现在 api.ts 与 storeStreamConnection.ts?
9. 本体层:是否改了 `ontology/` 声明?若改,`registry.py --write-all` 三类生成物是否同批再生成提交(严禁手改生成物)?
10. 深层模块方向:新代码是否收敛进既有单点深模块(run_agent、api.ts、storeCart),而非增加平行浅入口?

## 质量链

11. 测试:pytest 契约(改动面)/ vitest(与被测文件同目录)/ e2e(身份注入参数字面量)是否覆盖?播种脚本是否断言行数(无断言 = 假绿)?
12. Lint:`ruff check .` 两服务全目录与 CI 同口径;biome 用仓库版且 pathspec 限定。
13. 提交:信息只写说明本身,无尾注署名;并行会话下 add 后立即 commit。
14. 文档:行为变更是否回填 `.claude/rules/` 对应册与新代理路径的 `deploy/nginx.conf` 镜像(新代理路径必须同批,契约 test_deploy_nginx_contract.py)?
