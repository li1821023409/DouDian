#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 _下载清单.json 生成「榜单 → 商品文件夹」对照表，便于人工核对。"""
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(HERE, "..", "带货短视频")
MF = os.path.join(OUT_ROOT, "_下载清单.json")
MD = os.path.join(OUT_ROOT, "_榜单对照_1-10.md")


def main():
    d = json.load(open(MF, encoding="utf-8"))
    items = sorted(d["items"], key=lambda x: x.get("rank") or 0)

    lines = ["# 短视频带货榜 1-10 · 下载对照表", ""]
    lines.append("生成时间：%s" % d.get("generated_at"))
    lines.append("")
    lines.append("输出目录：`D:\\Data\\DouDian\\带货短视频`"
                 "（每个商品一个文件夹，文件夹名 = 商品名；"
                 "文件名 = 文件夹名_序号，如 `<商品名>_01.mp4`）")
    lines.append("")
    lines.append("| 排名 | 商品名 | 价格 | 应下 | 实下 | 文件夹 |")
    lines.append("|---|---|---|---|---|---|")

    tot_expect = tot_got = 0
    for it in items:
        dd = os.path.join(OUT_ROOT, it["dir"])
        # 只数「原片」：排除去水印成品和编码中断留下的 .part 残片
        got = len([f for f in glob.glob(os.path.join(dd, "*.mp4"))
                   if "_去水印版" not in os.path.basename(f)
                   and not f.endswith(".part.mp4")]) if os.path.isdir(dd) else 0
        exp = it["videos"]
        tot_expect += exp
        tot_got += got
        flag = "" if got == exp else " ⚠️缺%d" % (exp - got)
        lines.append("| %s | %s | ¥%s | %d | %d%s | %s |" % (
            it.get("rank"), it["title"], it.get("price", ""), exp, got, flag, it["dir"]))

    lines.append("")
    lines.append("**合计**：应下 %d 条，实下 %d 条。" % (tot_expect, tot_got))
    lines.append("")
    lines.append("> 缺的 2 条属于「AIGC」标记视频，晓风插件没给直链"
                 "（全榜 200 个商品中有 67 个存在这类条目），要补需进商品详情页单独取。")

    open(MD, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    print("\n已写入: %s" % os.path.abspath(MD))


if __name__ == "__main__":
    main()
