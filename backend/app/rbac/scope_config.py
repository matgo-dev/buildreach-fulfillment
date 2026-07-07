"""数据范围(scope)配置 + 查表函数。

v3 §4 设计:
- 权限点回答"能不能做",scope 回答"看哪些数据"
- scope 是简单查表 (角色, 资源域) → ALL/ORG/OWN/NONE
- 不做策略引擎、不支持优先级、不支持表达式 DSL

M0 裁剪:仅保留机制(Scope 枚举 + get_scope() 查表函数),业务资源域清单
(RESOURCES / ROLE_RESOURCE_SCOPE)清空 —— 履约系统基座本期无需资源域隔离。
"""
from __future__ import annotations

from enum import Enum


class Scope(str, Enum):
    """数据范围。"""
    ALL = "ALL"       # 全平台数据(无 WHERE 过滤)
    ORG = "ORG"       # 本组织数据
    OWN = "OWN"       # 本人/本企业数据
    NONE = "NONE"     # 无访问权


# 资源域权威清单 —— M0 无业务资源域,留空
RESOURCES: tuple[str, ...] = ()

# 角色 × 资源域 → scope 值 —— M0 留空
ROLE_RESOURCE_SCOPE: dict[str, dict[str, Scope]] = {}


def get_scope(role_codes: list[str], resource: str) -> Scope:
    """根据用户角色 + 资源域查 scope。多角色取**最宽松**(ALL > ORG > OWN > NONE)。"""
    if resource not in RESOURCES:
        return Scope.NONE
    rank = {Scope.NONE: 0, Scope.OWN: 1, Scope.ORG: 2, Scope.ALL: 3}
    best = Scope.NONE
    for r in role_codes:
        s = ROLE_RESOURCE_SCOPE.get(r, {}).get(resource, Scope.NONE)
        if rank[s] > rank[best]:
            best = s
    return best
