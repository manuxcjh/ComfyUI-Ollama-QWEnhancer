"""输出清洗（P2）——移植自 ``../ComfyUI-QwenVL/py/AILab_OutputCleaner.py``。

该上游模块**没有** ``NODE_CLASS_MAPPINGS``，是纯文本清洗工具，因此属于
「抽取复用」而非节点删除。对 Ollama 后端尤其必要：思考型模型经常把
`` thinking...<｜end▁of▁thinking｜>`` 或规划性文字混进正文，直接接到下游会污染 prompt。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

__all__ = ["OutputCleanConfig", "clean_model_output"]


@dataclass(frozen=True)
class OutputCleanConfig:
    """清洗开关组合。"""

    mode: str = "prompt"
    strip_think: bool = True
    strip_code_fences: bool = True
    strip_role_prefixes: bool = True
    strip_json_wrappers: bool = True
    strip_leading_preamble: bool = True
    strip_planning: bool = True
    normalize_punctuation: bool = True
    keep_first_paragraph_only: bool = False


_PUNCT_MAP = str.maketrans(
    {"’": "'", "‘": "'", "“": '"', "”": '"', "—": "-", "–": "-", "…": "...", "\u00a0": " "}
)

_ROLE_PREFIX_RE = re.compile(r"^\s*(assistant|final|output|response|result|prompt)\s*:\s*", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^\s*```[\w-]*\s*$", re.IGNORECASE)

# 思考块。相比上游额外覆盖两种真实世界的形态：
#   1) <thinking>...</thinking>（不只 <think>）
#   2) Qwen 系思考型模型的 <｜end▁of▁thinking｜> 结束符
#      （全角竖线 U+FF5C、下八分之一块 U+2581），且可能没有配对的开始标签。
_THINK_OPEN = r"<think(?:ing)?[^>]*>"
_THINK_CLOSE = r"</think(?:ing)?\s*>"
_QWEN_THINK_END = "<[\uff5c|]\\s*end[\\u2581_]?of[\\u2581_]?thinking\\s*[\uff5c|]>"

_THINK_BLOCK_RE = re.compile(
    f"(?:{_THINK_OPEN}).*?(?:{_THINK_CLOSE}|{_QWEN_THINK_END})",
    flags=re.IGNORECASE | re.DOTALL,
)
_THINK_OPEN_RE = re.compile(_THINK_OPEN, flags=re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(_THINK_CLOSE, flags=re.IGNORECASE)
_THINK_END_ONLY_RE = re.compile(_QWEN_THINK_END, flags=re.IGNORECASE)

_MARKER_RE = re.compile(r"(?im)^\s*(final|final answer|answer|output|result|prompt)\s*[:\-]\s*")
_IM_TOKEN_RE = re.compile(r"(?i)<\|?im_(start|end)\|?>|<im_(start|end)>|<\|endoftext\|>")
_PLANNING_RE = re.compile(
    r"(?is)\b("
    r"i\s+(should|need|must|will|want|am\s+going\s+to|have\s+to)\b|"
    r"let's\b|"
    r"first\b|next\b|then\b|"
    r"wait\b|"
    r"so\s+i\s+need\s+to\b|"
    r"i\s+should\s+focus\s+on\b"
    r")"
)


def clean_model_output(text: str, config: OutputCleanConfig | None = None) -> str:
    """按配置清洗模型输出；空输入返回空串。"""
    if not text:
        return ""

    cfg = config or OutputCleanConfig()
    cleaned = (text or "").strip()

    cleaned = _IM_TOKEN_RE.sub("", cleaned).strip()

    if cfg.strip_think:
        # 1) 完整思考块（含 Qwen 的 <｜end▁of▁thinking｜> 收尾）
        cleaned = _THINK_BLOCK_RE.sub("", cleaned)
        cleaned = _THINK_CLOSE_RE.sub("", cleaned)
        # 2) 只剩结束符：说明开始部分被截断，丢弃结束符之前的全部内容
        if _THINK_END_ONLY_RE.search(cleaned):
            cleaned = _THINK_END_ONLY_RE.split(cleaned)[-1]
        # 3) 只剩开标签（被截断的思考段）：丢弃其所在段落
        if _THINK_OPEN_RE.search(cleaned):
            cleaned = _THINK_OPEN_RE.sub("", cleaned)
            parts = re.split(r"\n\s*\n", cleaned, maxsplit=1)
            if len(parts) == 2:
                cleaned = parts[1]
        cleaned = cleaned.strip()

    cleaned = _IM_TOKEN_RE.sub("", cleaned).strip()

    if cfg.strip_code_fences and "```" in cleaned:
        lines = [ln for ln in cleaned.splitlines() if not _CODE_FENCE_RE.match(ln)]
        cleaned = "\n".join(lines).strip()

    if cfg.strip_json_wrappers:
        maybe = _extract_from_json(cleaned, mode=cfg.mode)
        if maybe is not None:
            cleaned = maybe.strip()

    if cfg.strip_leading_preamble:
        cleaned = _drop_preamble(cleaned).strip()

    if cfg.strip_planning and cfg.mode == "prompt":
        without_planning = _strip_planning_paragraphs(cleaned)
        if without_planning:
            cleaned = without_planning

    if cfg.strip_role_prefixes:
        lines = cleaned.splitlines()
        if lines:
            lines[0] = _ROLE_PREFIX_RE.sub("", lines[0])
        cleaned = "\n".join(lines).strip()

    cleaned = _MARKER_RE.sub("", cleaned).strip()

    if cfg.normalize_punctuation:
        cleaned = cleaned.translate(_PUNCT_MAP)

    if cfg.keep_first_paragraph_only:
        parts = re.split(r"\n\s*\n", cleaned, maxsplit=1)
        cleaned = parts[0].strip()

    return cleaned


def _extract_from_json(text: str, mode: str) -> str | None:
    candidate = text.strip()
    if not candidate or not (candidate.startswith("{") and candidate.endswith("}")):
        return None
    try:
        payload = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    preferred = (
        ["prompt", "final", "output", "text", "content"]
        if mode == "prompt"
        else ["text", "content", "output", "final"]
    )
    for key in preferred:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _drop_preamble(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text

    keep_from = 0
    for i, line in enumerate(lines[:20]):
        if _MARKER_RE.match(line):
            keep_from = i
        if re.search(r"(?i)\bhere(?:'s| is)\b", line) and i < 6:
            keep_from = max(keep_from, i + 1)

    return "\n".join(lines[keep_from:]).strip()


def _strip_planning_paragraphs(text: str) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    if not paragraphs:
        return ""

    kept: list[str] = []
    dropping = True
    for paragraph in paragraphs:
        is_planning = bool(_PLANNING_RE.search(paragraph))
        if dropping and is_planning:
            continue
        dropping = False
        kept.append(paragraph)

    # 全部内容都像规划时，不要清空输出
    if not kept:
        return text.strip()
    return "\n\n".join(kept).strip()
