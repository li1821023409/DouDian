#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把仓库里的技能「说明书」安装到 OpenClaw 的技能目录。

设计约定（2026-10 起）：
    · 仓库 `scripts/` 是**唯一**代码真源
    · 技能目录 `抖店管理工作流/skills/<技能名>/` 只放 SKILL.md 等文档，**不放脚本**
    · OpenClaw 只读 `~/.openclaw/workspace/skills/<技能名>/`，装进去的也只有文档

SKILL.md 里的 `{{PROJ}}` 占位符会在安装时替换成本仓库的实际路径，
这样仓库换机器 / 换盘符都不用改文档。

用法：
    D:/Install/Python/python.exe scripts/install_skills.py
    D:/Install/Python/python.exe scripts/install_skills.py --dry-run
"""
import argparse
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "抖店管理工作流" / "skills"
DST = Path.home() / ".openclaw" / "workspace" / "skills"
# 备份放在 skills 目录**外面**：skills/ 下任何带 SKILL.md 的子目录都会被当成技能加载
BAK_ROOT = Path.home() / ".openclaw" / "skill-backups"

# 技能名 -> 该技能目录下要装到 C 盘的文档（相对技能目录的路径）
SKILLS = {
    "doudian-export": ["SKILL.md"],
    "compass-video-rank": ["SKILL.md", "脚本清单.md"],
}

PLACEHOLDER = "{{PROJ}}"


def render(text: str) -> str:
    """把占位符换成本仓库的实际路径（统一正斜杠，bash / Python 都认）。"""
    return text.replace(PLACEHOLDER, PROJ.as_posix())


def main() -> int:
    ap = argparse.ArgumentParser(description="安装技能说明书到 OpenClaw 目录")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    ap.add_argument("--no-backup", action="store_true", help="不备份已有技能")
    args = ap.parse_args()

    print(f"仓库根目录: {PROJ}")
    print(f"源目录:     {SRC}")
    print(f"目标:       {DST}")
    if not SRC.exists():
        print(f"✗ 源目录不存在：{SRC}")
        return 1

    ok = fail = 0
    for name, docs in SKILLS.items():
        s = SRC / name
        d = DST / name
        if not s.exists():
            print(f"✗ 仓库里没有 {name}，跳过")
            fail += 1
            continue

        missing = [x for x in docs if not (s / x).exists()]
        if missing:
            print(f"✗ {name} 缺少 {missing}，跳过")
            fail += 1
            continue

        print(f"\n--- {name}")
        for rel in docs:
            print(f"  {rel}")

        if args.dry_run:
            print(f"  [dry-run] 将安装 {len(docs)} 个文档到 {d}")
            continue

        # 整目录重建：确保技能目录里不会残留上一版的 scripts/ 等文件
        if d.exists() and not args.no_backup:
            bak = BAK_ROOT / d.name
            if bak.exists():
                shutil.rmtree(bak)
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(d, bak)
            print(f"  已备份旧版本 → {bak}")
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

        for rel in docs:
            target = d / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render((s / rel).read_text(encoding="utf-8")),
                              encoding="utf-8")

        # 校验：不能有没替换掉的占位符
        left = [rel for rel in docs if PLACEHOLDER in (d / rel).read_text(encoding="utf-8")]
        if left:
            print(f"  ✗ 占位符未替换：{left}")
            fail += 1
            continue
        print(f"  ✓ 已安装 {len(docs)} 个文档（脚本仍只在仓库 scripts/）")
        ok += 1

    print(f"\n{'=' * 56}")
    if args.dry_run:
        print("dry-run 结束，未做任何改动")
    elif ok:
        print(f"安装完成：{ok} 个技能")
        print("OpenClaw 每次会话重新读取 SKILL.md，一般不用重启。")
    else:
        print("没有技能被安装")
    print("=" * 56)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
