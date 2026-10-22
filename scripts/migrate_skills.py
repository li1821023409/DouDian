#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「短视频带货榜」章节从 doudian-export 技能迁到 compass-video-rank 技能，
让两个技能各司其职：

  doudian-export       → 只负责商品数据导出
  compass-video-rank   → 短视频榜单：打开 / 下载 / 去水印 / 删除本地视频
"""
import shutil
import sys
from pathlib import Path

OC = Path(r"C:\Users\18210\.openclaw\workspace\skills")
DE = OC / "doudian-export" / "SKILL.md"
CV = OC / "compass-video-rank" / "SKILL.md"

MARK = "# 短视频带货榜：下载 / 去水印 / 清理"

DE_DESC = ('description: 自动整理抖店数据——导出货架商品数据表到本地目录。当用户提到'
           '"导出抖店商品数据""整理抖店数据""抖店商品表格""自动整理抖店数据""执行抖店工作流"时使用。'
           '必须直接运行现成脚本，不要手工操作浏览器。短视频榜单相关（打开/下载/去水印/删除）走 '
           'compass-video-rank 技能。')

CV_DESC = ('description: 抖店电商罗盘短视频带货榜——打开榜单页、批量下载带货短视频、'
           '批量去水印、清理本地视频。当用户说"打开短视频页面""打开短视频榜单""看看爆火带货短视频"'
           '"筛选爆火短视频""罗盘短视频榜""下载带货榜短视频""跑短视频带货流水线"'
           '"删除本地带货短视频"时使用。必须直接运行现成脚本，不要手工操作浏览器。')


def set_description(text, new_line):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("description:"):
            lines[i] = new_line
            break
    return "\n".join(lines)


def main():
    for p in (DE, CV):
        if not p.exists():
            print(f"✗ 找不到 {p}")
            return 1
        shutil.copy2(p, str(p) + ".bak")

    de = DE.read_text(encoding="utf-8")
    idx = de.find(MARK)
    if idx < 0:
        print("· doudian-export 里没有短视频章节，跳过迁移")
        section = None
    else:
        section = de[idx:]
        # 往回吃掉紧邻的分隔线
        head = de[:idx].rstrip()
        while head.endswith("---"):
            head = head[:-3].rstrip()
        de_new = head + ("\n\n> **短视频榜单相关**（打开榜单页 / 下载带货短视频 / 去水印 / 删除本地视频）"
                         "请走 `compass-video-rank` 技能。\n")
        DE.write_text(de_new, encoding="utf-8")
        print(f"✓ 已从 doudian-export 移出 {len(section)} 字符")

    if section:
        cv = CV.read_text(encoding="utf-8")
        if MARK in cv:
            print("· compass-video-rank 已有该章节，不重复追加")
        else:
            CV.write_text(cv.rstrip() + "\n\n---\n\n" + section, encoding="utf-8")
            print(f"✓ 已追加到 compass-video-rank（现 {len(section)} 字符）")

    # 更新两个技能的 description
    DE.write_text(set_description(DE.read_text(encoding="utf-8"), DE_DESC), encoding="utf-8")
    CV.write_text(set_description(CV.read_text(encoding="utf-8"), CV_DESC), encoding="utf-8")

    print("\n--- 结果 ---")
    for p in (DE, CV):
        t = p.read_text(encoding="utf-8")
        print(f"{p.parent.name}: {len(t)} 字符")
        print(f"  短视频章节: {t.count(MARK)} 次   删除触发词: {t.count('删除本地带货短视频')} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
