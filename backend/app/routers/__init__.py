"""业务路由汇总：固定前缀路由必须先于通用资源路由注册。"""
from __future__ import annotations

from app.routers import cross_links, resource, review_router

ROUTERS = [cross_links, review_router, resource]
