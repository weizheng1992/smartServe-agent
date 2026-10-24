-- 2026-10-24 工作台收敛(4d36136)已种库一次性 SQL —— ensure_menu_seed 只增不改,
-- 已种库的 m-agent-desk / m-live-desk 两行仍持旧名与旧路由,菜单呈现与种子源
-- DEFAULT_MENUS 漂移。在 engine 库(agent_platform)执行;幂等,可重复跑。
-- 执行后建议重启网关或等菜单树接口下次读库(菜单查询无缓存,即时生效)。
UPDATE menus SET name = '客服工作台'
 WHERE id = 'm-agent-desk' AND business_id = 'aurora' AND name <> '客服工作台';

UPDATE menus SET name = '待办审核', route = '/approvals'
 WHERE id = 'm-live-desk' AND business_id = 'aurora'
   AND (name <> '待办审核' OR route IS DISTINCT FROM '/approvals');
