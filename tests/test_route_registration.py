"""G4 门控：HTTP 路由注册与端到端行为（用真实 aiohttp 模拟 ComfyUI）。

ComfyUI 当前没有在运行，因此这里注入一个假的 ``server`` 模块，
其 ``PromptServer.instance.routes`` 是**真实的** ``aiohttp.web.RouteTableDef``
——与 ComfyUI ``server.py:262`` 的写法一致。

覆盖点
------
1. 路由确实被注册（早期版本用 ``routes.resources()`` 判断，而
   ``RouteTableDef`` 没有该方法，会导致路由**永远注册不上**）
2. 重复调用 ``register_routes()`` 幂等，不产生重复路由
3. ``app.add_routes(routes)`` 不抛 ``RuntimeError``（即 R2 已被规避）
4. 接口契约：成功 / 失败两种响应形态
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

ROUTE = "/ollama_qwenhancer/list_models"


def _install_fake_comfy_server():
    """注入最小可用的 ``server`` 模块，模拟 ComfyUI 的 PromptServer。"""

    class _PromptServer:
        instance = None

        def __init__(self):
            # 与 ComfyUI server.py:262-263 一致：RouteTableDef
            self.routes = web.RouteTableDef()

    _PromptServer.instance = _PromptServer()
    module = types.ModuleType("server")
    module.PromptServer = _PromptServer
    sys.modules["server"] = module
    return _PromptServer.instance


_server = _install_fake_comfy_server()

from _pkgload import load_package  # noqa: E402

_pkg = load_package()  # 导入即触发 register_routes()

#: 目标服务与模型与节点默认值保持一致（可由 QWE_OLLAMA_URL / config/local.json 覆盖）
URL = _pkg.core.types.DEFAULT_URL
MODEL = _pkg.core.types.DEFAULT_MODEL


def _matching_routes():
    return [d for d in _server.routes if getattr(d, "path", None) == ROUTE]


# --------------------------------------------------------------------------
# 注册行为
# --------------------------------------------------------------------------
def test_route_registered_exactly_once():
    routes = _matching_routes()
    assert len(routes) == 1, f"期望恰好 1 条 {ROUTE}，实际 {len(routes)}：{routes}"
    assert str(getattr(routes[0], "method", "")).upper() == "POST"
    print(f"      已注册路由：{routes[0]}")


def test_register_routes_is_idempotent():
    before = len(_matching_routes())
    assert _pkg.server.register_routes() is True
    assert _pkg.server.register_routes() is True
    after = len(_matching_routes())
    assert before == after == 1, f"重复注册产生了 {after} 条路由"


def test_add_routes_does_not_raise():
    """R2 回归：重复路由会让 add_routes 抛 RuntimeError。"""
    app = web.Application()
    app.add_routes(_server.routes)
    assert app is not None
    print("      app.add_routes() 未抛 RuntimeError（R2 已规避）")


def test_route_path_is_namespaced():
    assert ROUTE.startswith("/ollama_qwenhancer/"), ROUTE
    assert ROUTE != "/ollama/get_models", "不得复用 comfyui-ollama 的路由"


# --------------------------------------------------------------------------
# 接口契约（真实 HTTP 往返）
# --------------------------------------------------------------------------
def test_list_models_endpoint_success():
    async def scenario():
        app = web.Application()
        app.add_routes(_server.routes)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(ROUTE, json={"url": URL, "vision_only": True})
            assert resp.status == 200, resp.status
            return await resp.json()

    data = asyncio.run(scenario())
    assert data["error"] is None, data["error"]
    names = {m["name"] for m in data["models"]}
    assert MODEL in names, f"{MODEL} 不在 vision 模型列表中：{sorted(names)}"
    assert all(m.get("vision") for m in data["models"]), "vision_only 过滤未生效"
    print(f"      vision_only 返回 {len(names)} 个模型")


def test_list_models_endpoint_reports_error_without_500():
    """不可达地址应回传可读 error，而不是 500。"""

    async def scenario():
        app = web.Application()
        app.add_routes(_server.routes)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(ROUTE, json={"url": "http://127.0.0.1:59999"})
            return resp.status, await resp.json()

    status, data = asyncio.run(scenario())
    assert status == 200, f"应为 200（错误放在 body 里），实际 {status}"
    assert data["error"], "应回传错误信息"
    assert "无法连接" in data["error"], data["error"]
    print(f"      错误路径正确回传：{data['error'].splitlines()[0]}")


def test_list_models_endpoint_tolerates_bad_body():
    """非 JSON 请求体不应让路由崩溃。"""

    async def scenario():
        app = web.Application()
        app.add_routes(_server.routes)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(ROUTE, data=b"not json", headers={"Content-Type": "text/plain"})
            return resp.status, await resp.json()

    status, data = asyncio.run(scenario())
    assert status == 200, status
    # 空 body -> url 为 None -> 回退到默认主机；此处只要求结构完整不崩溃
    assert "models" in data and "error" in data


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    sys.exit(1 if failed else 0)
