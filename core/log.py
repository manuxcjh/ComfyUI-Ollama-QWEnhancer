"""统一日志出口（控制台噪声治理）。

背景：节点每次执行都打印一行会让 ComfyUI 控制台在批量/循环运行时刷屏。
本模块把本包的所有输出收敛到一个开关上。

级别由环境变量 ``QWE_LOG`` 控制（默认 ``warn``）：

| 值 | 输出内容 |
| --- | --- |
| ``error`` | 仅错误 |
| ``warn``（默认） | 错误 + 告警 |
| ``info`` | 追加一次性加载信息与每次执行摘要 |
| ``debug`` | 追加请求/响应明细 |

另外提供 :func:`warn_once`：同一类告警只打印一次，避免逐次运行重复刷屏。
"""

from __future__ import annotations

import os

__all__ = ["error", "warn", "warn_once", "info", "debug", "level", "reset_once"]

_LEVELS = {"error": 0, "warn": 1, "info": 2, "debug": 3}

_PREFIX = "[OllamaQWEnhancer]"

_level_name = (os.environ.get("QWE_LOG") or "warn").strip().lower()
_level = _LEVELS.get(_level_name, 1)

_once_seen: set[str] = set()


def level() -> str:
    """返回当前日志级别名。"""
    return _level_name if _level_name in _LEVELS else "warn"


def error(message: str) -> None:
    """错误：始终输出。"""
    print(f"{_PREFIX}[ERROR] {message}")


def warn(message: str) -> None:
    """告警：``error`` 级别下静默。"""
    if _level >= _LEVELS["warn"]:
        print(f"{_PREFIX}[WARN] {message}")


def warn_once(key: str, message: str) -> None:
    """同类告警只打印一次（``key`` 用于去重）。"""
    if key in _once_seen:
        return
    _once_seen.add(key)
    warn(message)


def info(message: str) -> None:
    """信息：默认不输出，``QWE_LOG=info`` 时可见。"""
    if _level >= _LEVELS["info"]:
        print(f"{_PREFIX} {message}")


def debug(message: str) -> None:
    """调试：仅 ``QWE_LOG=debug`` 时输出。"""
    if _level >= _LEVELS["debug"]:
        print(f"{_PREFIX}[DEBUG] {message}")


def reset_once() -> None:
    """清空 ``warn_once`` 去重表（测试用）。"""
    _once_seen.clear()
