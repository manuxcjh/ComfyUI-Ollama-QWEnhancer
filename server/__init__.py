"""ComfyUI 服务端扩展（P4）。"""

from __future__ import annotations

from .routes import ROUTE_PATH, register_routes

__all__ = ["ROUTE_PATH", "register_routes"]
