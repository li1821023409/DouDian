#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 AGENTS.md / SKILL.md 里引用的脚本路径是否真实存在。

背景（2026-10-26 事故）
    AGENTS.md 里写的是 `skills/doudian-export/scripts/*.py`，而技能目录下的
    scripts 副本早已删除。agent 照着执行 → 文件不存在 → 它开始自己找：
    tool_search 拉全量工具清单（1.3 万字符）+ 连续 process poll 40 多次，
    单轮把上下文顶到 22k token，几轮后整体超出 32k 上限，会话直接卡死。

    文档里的路径是给 agent 照着执行的，写错一个就等于埋一颗雷。
    所以每次改完 AGENTS.md / SKILL.md，跑一遍本脚本。

用法：
    D:/Install/Python/python.exe scripts/check_agents_md.py
    D:/Install/Python/python.exe scripts/check_agents_md.py --path 某个.md
退出码：0 = 全部有效；1 = 存在失效路径
"""
import argparse
import re
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SKILLS = PROJ / "抖店管理工作流" / "skills"

DEFAULT_TARGETS = [
    Path.home() / ".openclaw" / "workspace" / "AGENTS.md",
    SKILLS / "compass-video-rank" / "SKILL.md",
    SKILLS / "compass-video-rank" / "脚本清单.md",
    SKILLS / "doudian-export" / "SKILL.md",
]

# 抓形如 D:\a\b.py / D:/a/b.exe 的绝对路径；遇到空白/引号/中文标点即截断。
# 不只查 .py：文档里让 agent 直接执行的 python.exe、ffmpeg.exe、.bat 写错同样致命。
PAT = re.compile(r"[A-Za-z]:[\\/][^\s\"'|<>()（），。；]*?\.(?:py|exe|bat)")

# SKILL.md 里用占位符表示仓库位置，安装时才替换成本机实际路径
PLACEHOLDER = "{{PROJ}}"

# 文档里给读者填空的示例路径（如 xxx.py），不是真实文件，不做校验
FAKE_HINTS = ("xxx", "...", "你的", "example")


def check(md: Path) -> tuple[int, int]:
    """返回 (有效数, 失效数)。文件不存在时按 0/0 处理（换机器属正常）。"""
    print(f"\n=== {md} ===")
    if not md.exists():
        print("  -- 文件不存在，跳过")
        return 0, 0

    text = md.read_text(encoding="utf-8", errors="replace")
    text = text.replace(PLACEHOLDER, PROJ.as_posix())

    seen = set()
    ok = bad = skipped = 0
    for raw in sorted(set(PAT.findall(text))):
        local = raw.replace("\\", "/")
        if local in seen:
            continue
        seen.add(local)
        if any(h in local.lower() for h in FAKE_HINTS):
            skipped += 1
            continue
        if Path(local).exists():
            ok += 1
        else:
            bad += 1
            print(f"  ❌ {local}")

    if ok == 0 and bad == 0:
        print("  -- 未引用任何 .py / .exe / .bat 路径")
    else:
        tail = f"（另有 {skipped} 处示例占位已跳过）" if skipped else ""
        print(f"  {ok} 个有效，{bad} 个失效{tail}")
    return ok, bad


def main() -> int:
    ap = argparse.ArgumentParser(description="校验文档里引用的脚本路径")
    ap.add_argument("--path", action="append", default=None,
                    help="要校验的 md 文件，可重复；默认查 AGENTS.md 与两份 SKILL.md")
    args = ap.parse_args()

    targets = [Path(p) for p in args.path] if args.path else DEFAULT_TARGETS
    total_ok = total_bad = 0
    for md in targets:
        ok, bad = check(md)
        total_ok += ok
        total_bad += bad

    print("\n" + "=" * 52)
    if total_bad:
        print(f"✗ 共 {total_bad} 处失效（{total_ok} 处有效）")
        print("  文档里的路径必须是真实存在的文件，否则 agent 会照着失败并四处试探。")
        return 1
    print(f"✓ 全部有效（{total_ok} 处引用）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
