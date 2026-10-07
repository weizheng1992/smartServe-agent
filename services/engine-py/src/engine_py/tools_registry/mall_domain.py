"""商城域服务 — 兼容 shim(2026-10-07 拆解进 mall/ 子包,cart/ 先例)。

实现移步 ``tools_registry/mall/``(cart/catalog/addresses/fulfillment 四簇
Mixin 经 service 合并为一类);本模块只保留原导入路径(12 个消费方与测试
桩面),严禁新增业务。
"""

from .mall import MallDomainService

__all__ = ['MallDomainService']
