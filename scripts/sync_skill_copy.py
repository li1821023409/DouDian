#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把仓库里的技能定义渲染成「人类阅读版」存到项目里，并插入说明。

    抖店管理工作流/skills/doudian-export/SKILL.md
        → 抖店管理工作流/技能定义-商品导出（副本）.md
    抖店管理工作流/skills/compass-video-rank/SKILL.md
        → 抖店管理工作流/技能定义-短视频榜单（副本）.md

方向说明（2026-10 起）：
    · 唯一真源是仓库 `抖店管理工作流/skills/<技能>/SKILL.md`
    · `~/.openclaw/workspace/skills/` 里的是 install_skills.py 装过去的同一份内容
    · 本脚本只生成给人看的副本，把 {{PROJ}} 换成可直接复制的 Windows 路径

改技能时改仓库 SKILL.md，然后跑  install_skills.py（生效）+ 本脚本（留档）。
"""
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "抖店管理工作流" / "skills"
DOCS = PROJ / "抖店管理工作流"

PAIRS = [
    ("doudian-export", "技能定义-商品导出（副本）.md",
     "商品数据导出（导出货架商品 Excel）"),
    ("compass-video-rank", "技能定义-短视频榜单（副本）.md",
     "短视频带货榜（打开榜单 / 下载视频 / 去水印 / 删除本地视频）"),
]

PLACEHOLDER = "{{PROJ}}"


def note(skill_dir: str, summary: str):
    return [
        "",
        "> **📄 本文件是仓库技能的阅读版副本，仅供查阅与版本留档。**",
        f"> 用途：{summary}",
        f"> 真正生效的文件：`{SRC / skill_dir / 'SKILL.md'}`",
        f"> 所有脚本的唯一位置：`{PROJ / 'scripts'}`（技能定义里用绝对路径调用）",
        "> OpenClaw 实际读取的是 `~/.openclaw/workspace/skills/"
        f"{skill_dir}/SKILL.md`，由 `scripts/install_skills.py` 从本仓库安装。",
        "",
    ]


def sync_one(skill_dir: str, dst_name: str, summary: str) -> bool:
    src = SRC / skill_dir / "SKILL.md"
    dst = DOCS / dst_name
    if not src.exists():
        print(f"✗ 源文件不存在: {src}")
        return False

    text = src.read_text(encoding="utf-8").replace(PLACEHOLDER, str(PROJ))
    lines = text.split("\n")
    end, seen = None, 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            seen += 1
            if seen == 2:
                end = i
                break
    if end is None:
        print(f"✗ {skill_dir} 缺少 frontmatter")
        return False

    out = lines[:end + 1] + note(skill_dir, summary) + lines[end + 1:]
    dst.write_text("\n".join(out), encoding="utf-8")
    print(f"✓ skills/{skill_dir}/SKILL.md  →  {dst_name}  ({len(''.join(out))} 字符)")
    return True


def main() -> int:
    ok = True
    for d, name, summary in PAIRS:
        ok &= sync_one(d, name, summary)

    print("\n--- 校验 ---")
    for d, name, _ in PAIRS:
        p = DOCS / name
        if not p.exists():
            ok = False
            continue
        t = p.read_text(encoding="utf-8")
        bad = PLACEHOLDER in t
        print(f"  {name}: 占位符残留={bad} | 字面量 {len(t)} 字符")
        ok &= not bad
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
