"""商品导购 + 商品查询技能 — 兼容 shim(2026-10-07 拆解进 guide/ 子包)。

实现移步 ``skills/guide/``(cart/ 结构纪律:薄壳 skill + resolver 词族 +
recommendation 检索编排 + cards 渲染);本模块只保留原导入路径
(测试/plan_alignment 类名字符串/词族之家登记均经此处),严禁新增业务。"""

from .guide import ProductInquirySkill, ShoppingGuideSkill

__all__ = ["ProductInquirySkill", "ShoppingGuideSkill"]
