#!/usr/bin/env python3
"""Insert a blank line before Markdown lists that directly follow a paragraph line.

GitHub renders such lists anyway, but Python-Markdown (MkDocs) needs the blank
line. Code fences and tables are left alone. Usage: python3 scripts/fix-md-lists.py FILE...
"""

import re
import sys

LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")


def fix(text: str) -> str:
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and LIST_ITEM.match(line) and out:
            prev = out[-1]
            prev_is_text = prev.strip() and not LIST_ITEM.match(prev) and not prev.lstrip().startswith(("|", ">", "#", "<"))
            # Only top-level items after plain text; continuation lines of a list keep their place.
            if prev_is_text and not prev.startswith((" ", "\t")):
                out.append("")
        out.append(line)
    return "\n".join(out)


if __name__ == "__main__":
    for path in sys.argv[1:]:
        original = open(path, encoding="utf-8").read()
        fixed = fix(original)
        if fixed != original:
            open(path, "w", encoding="utf-8").write(fixed)
            print("fixed", path)
