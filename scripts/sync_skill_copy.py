#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 OpenClaw 的两个技能源文件同步成项目里的副本，并插入「本文件是副本」的说明。

    C:\\Users\\18210\\.openclaw\\workspace\\skills\\doudian-export\\SKILL.md
        → D:\\Data\\DouDian\\抖店管理工作流\\技能定义-商品导出（副本）.md
    C:\\Users\\18210\\.openclaw\\workspace\\skills\\compass-video-rank\\SKILL.md
        → D:\\Data\\DouDian\\抖店管理工作流\\技能定义-短视频榜单（副本）.md

改技能时永远改源文件，然后运行本脚本。
"""
import sys
from pathlib import Path

OC = Path(r"C:\Users\18210\.openclaw\workspace\skills")
DOCS = Path(r"D:\Data\DouDian\抖店管理工作流")

PAIRS = [
    ("doudian-export", "技能定义-商品导出（副本）.md",
     "商品数据导出（导出货架商品 Excel）"),
    ("compass-video-rank", "技能定义-短视频榜单（副本）.md",
     "短视频带货榜（打开榜单 / 下载视频 / 去水印 / 删除本地视频）"),
]


def note(skill_dir: str, summary: str):
    return [
        "",
        "> **📄 本文件是副本，仅供查阅与版本留档。**",
        f"> 用途：{summary}",
        f"> 真正生效的文件：`C:\\Users\\18210\\.openclaw\\workspace\\skills\\{skill_dir}\\SKILL.md`",
        "> OpenClaw 只读源文件。要改行为请改源文件，然后运行 `scripts/sync_skill_copy.py` 重新生成本文件。",
        "",
    ]


def sync_one(skill_dir: str, dst_name: str, summary: str):
    src = OC / skill_dir / "SKILL.md"
    dst = DOCS / dst_name
    if not src.exists():
        print(f"✗ 源文件不存在: {src}")
        return False

    lines = src.read_text(encoding="utf-8").split("\n")
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

    text = dst.read_text(encoding="utf-8")
    print(f"✓ {skill_dir}/SKILL.md  →  {dst_name}")
    print(f"    源 {len(''.join(lines))} 字符 / 副本 {len(text)} 字符")
    return True


def main():
    ok = True
    for d, name, summary in PAIRS:
        ok &= sync_one(d, name, summary)

    print("\n--- 副本校验 ---")
    for d, name, _ in PAIRS:
        p = DOCS / name
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        print(f"  {name}")
        print(f"    短视频章节 {t.count('# 短视频带货榜')} 次 | "
              f"删除触发词 {t.count('删除本地带货短视频')} 次 | "
              f"商品导出章节 {t.count('# 自动整理抖店数据')} 次")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
