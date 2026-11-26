"""业务路由汇总：专用清单接口先注册，通用资源路由兜底。"""
from __future__ import annotations

from app.routers import manifest, resource

ROUTERS = [manifest, resource]
