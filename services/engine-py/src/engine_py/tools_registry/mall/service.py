"""MallDomainService 兼容门面(2026-10-07 自 mall_domain.py 2 073 行拆解)。

四簇 Mixin 合并为一类:方法签名/类属性/patch 面(测试对
MallDomainService._cart_storage / _CART_REDIS_PREFIX 的类级 patch、内部
MallDomainService.X 全名互调)全部原样 —— 簇实现见同包 cart/catalog/
addresses/fulfillment;本壳严禁新增业务枝(cart/skill.py 同款纪律)。
"""

from __future__ import annotations

from . import addresses as _addresses_mod
from . import cart as _cart_mod
from . import catalog as _catalog_mod
from . import fulfillment as _fulfillment_mod
from .addresses import AddressesMixin
from .cart import CartMixin
from .catalog import CatalogMixin
from .fulfillment import FulfillmentMixin


class MallDomainService(CartMixin, CatalogMixin, AddressesMixin, FulfillmentMixin):
    """商城域服务(目录/购物车/地址/履约后)。静态方法命名空间;簇归属见各 Mixin。"""


# 成员展平:把四簇 Mixin 的方法/类属性拷入本类 __dict__ —— 部分测试以
# MallDomainService.__dict__["_embed_query"] 形式直读类字典打桩,纯继承不拷贝
# __dict__ 会 KeyError(2026-10-07 拆解首轮 59 red 的根因)。引用拷贝:
# _cart_storage 等可变容器仍是同一对象。
for _mixin in (CartMixin, CatalogMixin, AddressesMixin, FulfillmentMixin):
    for _name, _member in vars(_mixin).items():
        if _name.startswith("__"):
            continue
        setattr(MallDomainService, _name, _member)

# 回填类引用:簇函数体内的 MallDomainService.X 按调用时经本模块全局解析
for _m in (_cart_mod, _catalog_mod, _addresses_mod, _fulfillment_mod):
    _m.MallDomainService = MallDomainService
