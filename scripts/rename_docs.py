#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「抖店管理工作流」目录下的 md 文件改成一眼能区分用途的名字，并修正文件间的引用。"""
import os
import re
import sys
from pathlib import Path

DOCS = Path(r"D:\Data\DouDian\抖店管理工作流")

# 旧名 → 新名
RENAME = {
    "SKILL.md": "技能定义-商品导出（副本）.md",
    "SKILL-短视频榜单.md": "技能定义-短视频榜单（副本）.md",
    "抖店管理工作流说明.md": "使用说明-抖店管理工作流.md",
    "插件安装说明.md": "安装说明-晓风运营插件.md",
}

# 正文里需要替换的旧文件名 → 新文件名
REFS = {k: v for k, v in RENAME.items()}


def main():
    # 1. 重命名
    for old, new in RENAME.items():
        src, dst = DOCS / old, DOCS / new
        if src.exists():
            if dst.exists():
                print(f"! 目标已存在，跳过: {new}")
                continue
            os.rename(src, dst)
            print(f"✓ {old}  →  {new}")
        elif dst.exists():
            print(f"· 已是新名: {new}")
        else:
            print(f"✗ 找不到: {old}")

    # 2. 修正所有 md 里的旧文件名引用
    changed = []
    for p in DOCS.glob("*.md"):
        text = p.read_text(encoding="utf-8")
        origin = text
        for old, new in REFS.items():
            # 避免把新名里的子串再替换一次：只替换独立的旧名
            text = re.sub(rf"(?<![\w\u4e00-\u9fa5-]){re.escape(old)}(?![\w\u4e00-\u9fa5-])", new, text)
        if text != origin:
            p.write_text(text, encoding="utf-8")
            changed.append(p.name)
    if changed:
        print(f"\n更新了引用的文件: {', '.join(changed)}")

    # 3. 列出最终结果
    print("\n--- 目录内容 ---")
    for p in sorted(DOCS.glob("*.md")):
        first = ""
        for line in p.read_text(encoding="utf-8").split("\n"):
            if line.startswith("# "):
                first = line[2:].strip()
                break
        print(f"  {p.name:<34} {p.stat().st_size:>6}B  {first[:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
