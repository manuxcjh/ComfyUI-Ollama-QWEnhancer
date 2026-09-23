"""ComfyUI PromptServer 路由注册（P4）。

路由：``POST /ollama_qwenhancer/list_models``

⚠️ 不复用 ``/ollama/get_models``（comfyui-ollama 的路由）。ComfyUI 的
``PromptServer.instance.routes`` 是一个 ``aiohttp.web.RouteTableDef``，
重复注册同一 path+method 会在 ``app.add_routes()`` 时抛
``RuntimeError: Added route will never be executed, method POST is already registered``，
导致后加载的包整体崩溃。这是风险 R2 的具体规避措施。

请求体::

    {"url": "http://127.0.0.1:11434", "vision_only": true}

响应体::

    {"models": [{"name": "...", "vision": true, "family": "...", "parameter_size": "..."}],
     "error": null}

注意：``RouteTableDef`` **没有** ``resources()`` 方法（那是 ``UrlDispatcher`` 的 API），
只能迭代它拿到 ``RouteDef``（含 ``.path`` / ``.method``）。
"""

from __future__ import annotations
from ..core import log

ROUTE_PATH = "/ollama_qwenhancer/list_models"
ROUTE_METHOD = "POST"

_registered = False


async def _list_models_handler(request):
    """返回模型列表；错误以 ``error`` 字段回传，HTTP 状态保持 200。

    用 200 + error 而不是 4xx：前端据此展示可读提示，同时避免在浏览器
    控制台刷出网络错误。
    """
    from aiohttp import web

    from ..core import ollama_client

    try:
        data = await request.json()
    except Exception:
        data = {}

    url = (data or {}).get("url")
    vision_only = bool((data or {}).get("vision_only", False))

    try:
        models = ollama_client.list_models(url, vision_only=vision_only, probe_vision=True)
        return web.json_response({"models": models, "error": None})
    except ollama_client.OllamaError as exc:
        return web.json_response({"models": [], "error": str(exc)})
    except Exception as exc:  # 兜底：绝不让路由抛 500
        return web.json_response({"models": [], "error": f"未预期的错误：{exc}"})


def _route_exists(routes, path: str, method: str) -> bool:
    """判断路由是否已注册。

    同时兼容两种形态：

    * ``aiohttp.web.RouteTableDef``（ComfyUI 实际使用的类型）——可迭代出 ``RouteDef``
    * ``aiohttp.web.UrlDispatcher``（若某些发行版把 ``routes`` 换成 router）——用 ``resources()``
    """
    # 形态一：RouteTableDef（可迭代出 RouteDef）
    try:
        for item in routes:
            item_path = getattr(item, "path", None)
            if item_path != path:
                continue
            item_method = getattr(item, "method", None)
            if item_method is None or str(item_method).upper() == method.upper():
                return True
    except TypeError:
        pass

    # 形态二：UrlDispatcher
    resources = getattr(routes, "resources", None)
    if callable(resources):
        try:
            for resource in resources():
                if getattr(resource, "canonical", None) == path:
                    return True
        except Exception:
            pass

    return False


def register_routes() -> bool:
    """在 ComfyUI PromptServer 上注册路由。

    返回是否注册成功；任何失败都只打印告警，不影响节点加载。
    重复调用是幂等的。
    """
    global _registered
    if _registered:
        return True

    try:
        from server import PromptServer
    except Exception as exc:
        log.info(f"未在 ComfyUI 环境中运行，跳过 HTTP 路由注册（{exc}）")
        return False

    try:
        routes = PromptServer.instance.routes

        if _route_exists(routes, ROUTE_PATH, ROUTE_METHOD):
            _registered = True
            return True

        routes.post(ROUTE_PATH)(_list_models_handler)
        _registered = True
        log.info(f"已注册模型列表路由 {ROUTE_METHOD} {ROUTE_PATH}")
        return True
    except Exception as exc:
        log.error(f"路由注册失败：{exc}")
        return False


__all__ = ["ROUTE_PATH", "ROUTE_METHOD", "register_routes"]
