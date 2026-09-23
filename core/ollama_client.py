"""Ollama 访问封装（P2）。

职责边界：本模块是**唯一**直接与 ``ollama`` 客户端交互的地方，
节点层只做 widget → 本模块的映射，不处理任何网络或错误逻辑。

对外 API
--------
* :func:`normalize_host`  —— 容忍 ``127.0.0.1:11434`` 这类无 scheme 写法
* :func:`list_models`     —— 模型清单 + vision 能力标注（FR-02 / FR-03）
* :func:`capabilities`    —— 单模型能力（``/api/show``）
* :func:`resolve_model`   —— 容错解析模型名，失败时给出候选建议
* :func:`ensure_vision`   —— VL 节点前置校验
* :func:`run`             —— 统一的 generate 调用（图像 / 纯文本）

异常统一继承 :class:`OllamaError`，消息面向用户、可直接展示（NFR-04）。
"""

from __future__ import annotations

import difflib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable
from urllib.parse import urlparse

from .types import DEFAULT_URL
from . import log

__all__ = [
    "OllamaError",
    "OllamaUnavailable",
    "ModelNotFound",
    "ModelHasNoVision",
    "normalize_host",
    "list_models",
    "capabilities",
    "resolve_model",
    "ensure_vision",
    "build_options",
    "run",
]


# --------------------------------------------------------------------------
# 异常
# --------------------------------------------------------------------------
class OllamaError(RuntimeError):
    """所有 Ollama 相关错误的基类，消息可直接展示给用户。"""


class OllamaUnavailable(OllamaError):
    """无法连接 Ollama 服务。"""


class ModelNotFound(OllamaError):
    """请求的模型不在服务端。"""


class ModelHasNoVision(OllamaError):
    """模型不具备图像理解能力。"""


# --------------------------------------------------------------------------
# 主机地址
# --------------------------------------------------------------------------
def normalize_host(url: str | None) -> str:
    """把用户输入的地址规范成 ``scheme://host:port``。

    接受 ``127.0.0.1:11434``、``http://127.0.0.1:11434``、``127.0.0.1`` 三种写法。
    """
    raw = (url or "").strip() or DEFAULT_URL
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname:
        raise OllamaError(f"Ollama 地址无法解析：{url!r}，应为 http://主机:端口 形式。")
    scheme = parsed.scheme or "http"
    port = parsed.port or 11434
    return f"{scheme}://{parsed.hostname}:{port}"


def _client(url: str | None, timeout: float | None = None):
    """构造 ollama 客户端；依赖缺失或地址非法时抛出可读异常。

    ``timeout`` 用于 UI 侧探测（如节点下拉框初始化）时快速失败，
    避免 ComfyUI 启动被慢速网络阻塞。
    """
    try:
        from ollama import Client
    except ImportError as exc:  # pragma: no cover
        raise OllamaUnavailable(
            "未安装 ollama Python 客户端。请在 ComfyUI 所在环境执行："
            "pip install -r requirements.txt"
        ) from exc

    host = normalize_host(url)
    if timeout is not None:
        try:
            return Client(host=host, timeout=timeout)
        except TypeError:  # 老版本客户端不接受 timeout
            pass
    return Client(host=host)


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """兼容 pydantic 响应对象与普通 dict 的字段读取。"""
    if isinstance(obj, dict):
        return obj.get(name, default)
    value = getattr(obj, name, None)
    if value is None:
        getter = getattr(obj, "get", None)
        if callable(getter):
            try:
                value = getter(name, default)
            except Exception:
                value = default
    return default if value is None else value


def _translate(exc: Exception, host: str, model: str | None = None) -> OllamaError:
    """把底层异常翻译成面向用户的提示（NFR-04）。"""
    text = str(exc)
    low = text.lower()
    if "not found" in low or "no such model" in low:
        return ModelNotFound(
            f"模型 {model!r} 在 {host} 上不存在。"
            f"请用 `ollama pull {model}` 拉取，或在节点上点「🔄 刷新模型」重新选择。"
        )
    if any(
        k in low
        for k in ("connection", "refused", "timed out", "timeout", "unreachable", "resolve", "connect")
    ):
        return OllamaUnavailable(
            f"无法连接 Ollama 服务 {host}。请确认：\n"
            f"  1) 服务已启动（OLLAMA_HOST=0.0.0.0 ollama serve）；\n"
            f"  2) 地址与端口填写正确；\n"
            f"  3) 防火墙允许访问。\n原始错误：{text}"
        )
    return OllamaError(f"Ollama 调用失败（{host}{f' / {model}' if model else ''}）：{text}")


# --------------------------------------------------------------------------
# 能力探测（带 TTL 缓存，避免每次刷新都打满 /api/show）
# --------------------------------------------------------------------------
_CACHE_TTL = 60.0
_cache_lock = threading.Lock()
_caps_cache: dict[tuple[str, str], tuple[float, list[str]]] = {}


def capabilities(url: str | None, model: str, timeout: float | None = None) -> list[str]:
    """返回模型能力列表（如 ``["completion", "vision", ...]``）。"""
    host = normalize_host(url)
    key = (host, model)
    now = time.time()
    with _cache_lock:
        hit = _caps_cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return list(hit[1])

    client = _client(host, timeout=timeout)
    try:
        resp = client.show(model)
    except Exception as exc:
        raise _translate(exc, host, model) from exc

    caps = [str(c) for c in (_field(resp, "capabilities") or [])]
    with _cache_lock:
        _caps_cache[key] = (now, list(caps))
    return caps


# --------------------------------------------------------------------------
# 模型清单
# --------------------------------------------------------------------------
def _model_entry(item: Any) -> dict[str, Any]:
    name = _field(item, "model") or _field(item, "name") or ""
    details = _field(item, "details") or {}
    return {
        "name": str(name),
        "family": str(_field(details, "family", "") or ""),
        "parameter_size": str(_field(details, "parameter_size", "") or ""),
        "vision": None,  # 由 probe 阶段决定
    }


def list_models(
    url: str | None,
    vision_only: bool = False,
    probe_vision: bool = True,
    max_workers: int = 8,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """列出服务端模型；``probe_vision`` 时并发标注 ``vision`` 能力。

    ``vision_only=True`` 时只返回具备 vision 能力的模型（FR-03）。
    ``timeout`` 用于 UI 侧探测时快速失败。
    """
    host = normalize_host(url)
    client = _client(host, timeout=timeout)
    try:
        resp = client.list()
    except Exception as exc:
        raise _translate(exc, host) from exc

    entries = [_model_entry(m) for m in (_field(resp, "models") or [])]
    entries = [e for e in entries if e["name"]]

    if probe_vision and entries:
        # /api/show 很轻量（读 manifest），并发探测足够快
        def probe(entry: dict[str, Any]) -> dict[str, Any]:
            try:
                caps = capabilities(host, entry["name"])
                entry["vision"] = "vision" in caps
                entry["capabilities"] = caps
            except OllamaError:
                entry["vision"] = None
            return entry

        with ThreadPoolExecutor(max_workers=min(max_workers, len(entries))) as pool:
            entries = list(pool.map(probe, entries))

    if vision_only:
        entries = [e for e in entries if e.get("vision")]

    entries.sort(key=lambda e: e["name"].lower())
    return entries


def resolve_model(url: str | None, requested: str) -> str:
    """容错解析模型名：精确 → 忽略大小写 → 去 ``:latest`` → 唯一近似匹配。

    近似匹配设了两道闸，避免静默选错模型：
    * 相似度必须 ≥ ``0.85``
    * 且与第二名的差距 ≥ ``0.05``（即优势明确）

    典型场景：用户写成 ``qwen2.5vl-27B:7b``
    （相似度 0.95，第二名 0.79），可自动纠正为
    ``qwen2.5vl:7b``。
    """
    wanted = (requested or "").strip()
    if not wanted:
        raise ModelNotFound("未选择模型。请在节点上点「🔄 刷新模型」后选择一个模型。")

    host = normalize_host(url)
    available = [e["name"] for e in list_models(host, probe_vision=False)]

    if wanted in available:
        return wanted

    lower_map = {n.lower(): n for n in available}
    if wanted.lower() in lower_map:
        return lower_map[wanted.lower()]

    trimmed = wanted.split(":")[0].lower()
    for name in available:
        if name.split(":")[0].lower() == trimmed:
            return name

    # 唯一近似匹配：两道闸都通过才自动纠正
    scored = sorted(
        ((difflib.SequenceMatcher(None, wanted, name).ratio(), name) for name in available),
        reverse=True,
    )
    if scored:
        best_ratio, best_name = scored[0]
        second_ratio = scored[1][0] if len(scored) > 1 else 0.0
        if best_ratio >= 0.85 and (best_ratio - second_ratio) >= 0.05:
            log.warn_once(
                f"model-name-fix:{wanted}",
                f"模型名 {wanted!r} 不存在，已自动纠正为 {best_name!r}（相似度 {best_ratio:.2f}）",
            )
            return best_name

    suggestions = [name for _, name in scored[:3]]
    hint = ("\n最接近的候选：\n  - " + "\n  - ".join(suggestions)) if suggestions else ""
    listing = (
        "\n当前可用模型：\n  - " + "\n  - ".join(available)
        if available
        else "\n当前服务端没有任何模型。"
    )
    raise ModelNotFound(f"模型 {wanted!r} 不存在于 {host}。{hint}{listing}")


def ensure_vision(url: str | None, model: str) -> str:
    """VL 节点前置校验：模型必须支持 vision，否则给出可操作提示。"""
    host = normalize_host(url)
    caps = capabilities(host, model)
    if "vision" not in caps:
        raise ModelHasNoVision(
            f"模型 {model!r} 不支持图像理解（capabilities={caps}）。\n"
            f"请改选具备 vision 能力的模型（在节点上点「🔄 刷新模型」，"
            f"列表中以 👁 标记的即为多模态模型）。"
        )
    return model


# --------------------------------------------------------------------------
# 生成参数
# --------------------------------------------------------------------------
def build_options(
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    repetition_penalty: float | None = None,
    seed: int | None = None,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    """把节点参数映射为 Ollama ``options``（FR-07）。

    映射关系：``max_tokens→num_predict``、``repetition_penalty→repeat_penalty``，
    其余同名。``None`` 表示不发送，交由服务端默认值决定。
    """
    options: dict[str, Any] = {}
    if max_tokens is not None:
        options["num_predict"] = int(max_tokens)
    if temperature is not None:
        options["temperature"] = float(temperature)
    if top_p is not None:
        options["top_p"] = float(top_p)
    if repetition_penalty is not None:
        options["repeat_penalty"] = float(repetition_penalty)
    if seed is not None:
        options["seed"] = int(seed)
    if num_ctx is not None:
        options["num_ctx"] = int(num_ctx)
    return options


# --------------------------------------------------------------------------
# 推理
# --------------------------------------------------------------------------
def _is_think_unsupported(exc: Exception) -> bool:
    return "does not support thinking" in str(exc).lower()


def run(
    url: str | None,
    model: str,
    prompt: str,
    system: str | None = None,
    images: Iterable[str] | None = None,
    options: dict[str, Any] | None = None,
    keep_alive: str | int | None = None,
    think: bool = False,
    fmt: str = "",
    debug: bool = False,
) -> tuple[str, str | None]:
    """调用 ``/api/generate``，返回 ``(文本, 思考文本或 None)``。

    ``think`` **总是显式发送**。这一点很关键：思考型模型（如 Qwen3、
    DeepSeek-R1）在未指定 ``think`` 时默认开启思考，会把 ``num_predict``
    全部消耗在 ``thinking`` 上，导致 ``response`` 为空、``done_reason=length``。
    显式发送 ``think=False`` 才能拿到正文。

    若模型不支持思考而又要求 ``think=True``，Ollama 会返回 400，
    此时打印告警并以 ``think=False`` 重试，避免整条工作流失败。
    """
    host = normalize_host(url)
    client = _client(host)

    image_list = [i for i in (images or []) if i] or None

    kwargs: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "options": options or {},
        "think": bool(think),
    }
    if system:
        kwargs["system"] = system
    if image_list:
        kwargs["images"] = image_list
    if keep_alive is not None:
        kwargs["keep_alive"] = keep_alive
    if fmt in ("json", ""):
        kwargs["format"] = fmt

    if debug:
        log.debug(
            "请求 "
            f"host={host} model={model} system={system!r} "
            f"prompt={prompt[:200]!r} images={0 if not image_list else len(image_list)} "
            f"options={kwargs['options']} keep_alive={keep_alive} "
            f"think={think} format={fmt!r}"
        )

    try:
        resp = client.generate(**kwargs)
    except Exception as exc:
        if think and _is_think_unsupported(exc):
            log.warn_once(
                f"no-think:{model}",
                f"模型 {model!r} 不支持思考（thinking），已自动以 think=False 重试。",
            )
            kwargs.pop("think", None)
            try:
                resp = client.generate(**kwargs)
            except Exception as retry_exc:
                raise _translate(retry_exc, host, model) from retry_exc
        else:
            raise _translate(exc, host, model) from exc

    text = _field(resp, "response", "") or ""
    thinking = _field(resp, "thinking") if think else None

    # 空正文通常是 max_tokens 太小被思考内容吃光；同类告警只报一次，避免逐次刷屏
    if not text.strip() and _field(resp, "done_reason") == "length":
        log.warn_once(
            f"empty-response:{model}",
            f"模型 {model!r} 返回空正文且 done_reason=length："
            f"num_predict（当前 {kwargs['options'].get('num_predict')}）可能过小，"
            f"或思考内容占满了预算。请增大 max_tokens。",
        )

    if debug:
        log.debug(f"响应 thinking={(thinking or '')[:200]!r} response={text[:400]!r}")

    return text, thinking
