"""逐个跑扩展工具，确认不是"语法对但跑不起来"。"""
from __future__ import annotations

import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# preview 代码里写的是 `from runtime_sdk import NodeContext`，
# 所以要把 runtime 目录也放进搜索路径
sys.path.insert(0, str(ROOT / "backend" / "app" / "runtime"))

from backend.app.tool_presets import TOOL_PRESETS  # noqa: E402


class FakeCtx:
    def __init__(self, text: str = "", params: dict | None = None):
        self.text = text
        self.params = params or {}
        self.state: dict = {}


CASES = [
    ("hash_text", "hello", {"algo": "md5"}),
    ("uuid_gen", "", {"count": 3}),
    ("base64_codec", "hello world", {"action": "encode"}),
    ("regex_extract", "a=1 b=22 c=333", {"pattern": r"\d+", "text": "a=1 b=22 c=333"}),
    ("html_to_text", "<b>hi</b><script>x</script>there", {"html": "<b>hi</b><script>x</script>there"}),
    ("markdown_to_html", "# 标题\n\n**粗**", {"text": "# 标题\n\n**粗**"}),
    ("diff_text", "x", {"old": "a\nb", "new": "a\nc"}),
    ("dns_lookup", "example.com", {"domain": "example.com"}),
    ("wikipedia", "人工智能", {"query": "人工智能", "lang": "zh"}),
    ("open_meteo", "北京", {"city": "北京"}),
    ("github_api", "repos/openai/openai-python", {"path": "repos/openai/openai-python"}),
    ("python_repl", "", {"code": "print(6*7)"}),
]


def main():
    total = ok = 0
    for name, text, params in CASES:
        spec = TOOL_PRESETS.get(name)
        if not spec:
            print(f"✘ {name}: 预设不存在")
            continue
        total += 1
        scope: dict = {}
        try:
            exec(compile(spec["preview"], f"{name}.py", "exec"), scope)
            result = scope["run"](FakeCtx(text, params))
            text_out = str(result).replace("\n", " ")[:80]
            print(f"✔ {name:16s} → {text_out}")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"✘ {name:16s} → {type(exc).__name__}: {str(exc)[:80]}")
            if name in ("wikipedia", "open_meteo", "github_api"):
                traceback.print_exc(limit=1)
    print(f"\n{ok}/{total} 可执行")


if __name__ == "__main__":
    main()
