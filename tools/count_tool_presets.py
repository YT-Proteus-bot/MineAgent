"""统计 tool 节点可套用的预设：总数、按依赖分类。"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.tool_presets import TOOL_PRESETS  # noqa: E402

# 从 description / native 代码里推断依赖
KEY_PATTERNS = [
    (r"TAVILY_API_KEY", "需要 TAVILY_API_KEY"),
    (r"SERPER_API_KEY", "需要 SERPER_API_KEY"),
    (r"WOLFRAM_APP_ID", "需要 WOLFRAM_APP_ID"),
    (r"GITHUB_TOKEN", "可选 GITHUB_TOKEN"),
]
PKG_PATTERNS = [
    (r"import pypdf|from pypdf", "需要 pypdf"),
    (r"import docx|from docx", "需要 python-docx"),
    (r"import markdown\b", "需要 markdown"),
]


def classify(name: str, spec: dict) -> str:
    text = (spec.get("description") or "") + "\n" + (spec.get("native") or "")
    for pat, label in KEY_PATTERNS:
        if re.search(pat, text):
            return label
    for pat, label in PKG_PATTERNS:
        if re.search(pat, text):
            return label
    return "零依赖"


def main():
    buckets: dict[str, list[str]] = {}
    for name, spec in TOOL_PRESETS.items():
        buckets.setdefault(classify(name, spec), []).append(spec["label"])

    print(f"tool 节点可套用的预设总数：{len(TOOL_PRESETS)}\n")
    order = ["零依赖", "需要 markdown", "需要 pypdf", "需要 python-docx",
             "可选 GITHUB_TOKEN", "需要 TAVILY_API_KEY", "需要 SERPER_API_KEY",
             "需要 WOLFRAM_APP_ID"]
    for key in order:
        items = buckets.get(key) or []
        if not items:
            continue
        print(f"{key}（{len(items)} 个）：")
        for label in items:
            print(f"    {label}")
        print()


if __name__ == "__main__":
    main()
