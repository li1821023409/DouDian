#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把仓库里的技能源文件安装到 OpenClaw 的技能目录。

OpenClaw 只读取 `~/.openclaw/workspace/skills/<技能名>/`，而那部分不在 git 里，
所以换机器 / 重装 OpenClaw 后必须执行本脚本，否则技能不生效。

用法：
    D:\\Install\\Python\\python.exe scripts\\install_skills.py
    D:\\Install\\Python\\python.exe scripts\\install_skills.py --dry-run
"""
import argparse
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "抖店管理工作流" / "skills"
DST = Path.home() / ".openclaw" / "workspace" / "skills"

SKILLS = ["doudian-export", "compass-video-rank"]


def main():
    ap = argparse.ArgumentParser(description="安装技能到 OpenClaw 目录")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    ap.add_argument("--no-backup", action="store_true", help="不备份已有技能")
    args = ap.parse_args()

    print(f"源目录: {SRC}")
    print(f"目标:   {DST}")
    if not SRC.exists():
        print(f"✗ 源目录不存在：{SRC}")
        return 1

    ok = fail = 0
    for name in SKILLS:
        s = SRC / name
        d = DST / name
        if not s.exists():
            print(f"✗ 仓库里没有 {name}，跳过")
            fail += 1
            continue
        print(f"\n--- {name}")
        files = [p for p in s.rglob("*") if p.is_file()
                 and "__pycache__" not in p.parts]
        for f in files:
            rel = f.relative_to(s)
            print(f"  {rel}")
        if args.dry_run:
            print(f"  [dry-run] 将复制 {len(files)} 个文件到 {d}")
            continue

        if d.exists() and not args.no_backup:
            bak = d.with_name(d.name + ".bak")
            if bak.exists():
                shutil.rmtree(bak)
            shutil.copytree(d, bak)
            print(f"  已备份旧版本 → {bak.name}")
            shutil.rmtree(d)

        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            target = d / f.relative_to(s)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        print(f"  ✓ 已安装 {len(files)} 个文件")
        ok += 1

    print(f"\n{'='*56}")
    if args.dry_run:
        print("dry-run 结束，未做任何改动")
    elif ok:
        print(f"安装完成：{ok} 个技能")
        print("下一步：重启 OpenClaw 让技能重新加载，")
        print("        然后说「打开短视频榜单」验证是否生效。")
    else:
        print("没有技能被安装")
    print("=" * 56)
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
