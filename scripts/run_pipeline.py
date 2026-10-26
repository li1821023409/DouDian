#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抖音带货短视频 · 全流程流水线

    打开罗盘短视频榜 → 抓榜单直链 → 按商品分文件夹下载（含商品主图）
    → 统一为巨量千川素材规格 → 可选：批量去水印

⚠️ 千川规格**默认执行**：巨量千川对上传素材有硬性要求（竖版 720x1280 起、
码率 ≥516kbps、4~300s 等），下载到的原始直链经常不达标。这一步是原地
替换，文件名不变，不产生额外文件。确实不需要时加 `--no-qianchuan`。

⚠️ 去水印默认**不执行**：它很慢（长视频一条十几分钟），只有用户明确说
「去水印 / 跑一下去水印 / 处理后发我」时才加 `--dewatermark`。

用法：
    python scripts/run_pipeline.py --top 10                  # 默认：下载 + 统一千川规格
    python scripts/run_pipeline.py --top 10 --no-qianchuan   # 只下载，不转码
    python scripts/run_pipeline.py --top 10 --dewatermark    # 下载 + 去水印 + 统一规格
    python scripts/run_pipeline.py --top 10 --dewatermark --replace   # 去水印后删原片
    python scripts/run_pipeline.py --top 10 --skip-open      # 页面已打开且在第 1 页时跳过
    python scripts/run_pipeline.py --top 3 --dry-run         # 只打印计划，不执行
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path(r"D:\Data\DouDian")                 # 项目根（硬编码，脚本复制到别处也能跑）
SCRIPTS = PROJ / "scripts"
VC = PROJ / "video-cleaner"
PY_SYS = r"D:\Install\Python\python.exe"           # 纯标准库脚本用这个
PY_VENV = str(VC / ".venv" / "Scripts" / "python.exe")   # 需要 cv2/torch 的用这个


def run(cmd, desc, dry=False):
    print(f"\n{'='*60}\n▶ {desc}\n  {' '.join(cmd)}\n{'='*60}", flush=True)
    if dry:
        print("  [dry-run] 跳过执行")
        return True
    t0 = time.time()
    p = subprocess.run(cmd, cwd=str(PROJ))
    el = time.time() - t0
    if p.returncode != 0:
        print(f"✗ {desc} 失败（returncode={p.returncode}，耗时 {el:.0f}s）", flush=True)
        return False
    print(f"✓ {desc} 完成（{el:.0f}s）", flush=True)
    return True


def main():
    ap = argparse.ArgumentParser(description="抖音带货短视频流水线：榜单→下载（去水印可选）")
    ap.add_argument("--from", dest="from_rank", type=int, default=1,
                    help="起始排名（含），从 1 开始。例：--from 10")
    ap.add_argument("--to", dest="to_rank", type=int, default=0,
                    help="结束排名（含）。例：--to 15")
    ap.add_argument("--top", type=int, default=0,
                    help="等价于 --to（只下前 N 名，默认 10）")
    ap.add_argument("--skip-open", action="store_true", help="跳过打开榜单页")
    ap.add_argument("--skip-fetch", action="store_true", help="跳过抓取，复用已有 JSON")
    ap.add_argument("--dewatermark", action="store_true",
                    help="下载后执行去水印（默认不执行，用户明确要求去水印时才加）")
    ap.add_argument("--no-clean", action="store_true",
                    help="[已废弃] 现在默认就不去水印，保留此参数只为兼容旧命令")
    ap.add_argument("--replace", action="store_true",
                    help="去水印成功后删除原片（需同时加 --dewatermark）")
    ap.add_argument("--workers", type=int, default=6, help="下载并发")
    ap.add_argument("--shards", type=int, default=2, help="去水印并行进程数")
    ap.add_argument("--no-qianchuan", action="store_true",
                    help="不统一千川规格（默认会做：巨量千川素材有分辨率等硬性要求）")
    ap.add_argument("--jobs", type=int, default=4, help="千川转码并发（默认 4）")
    ap.add_argument("--clean", action="store_true",
                    help="跑之前先清空 带货短视频 目录（彻底删除，不保留旧产物）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    args = ap.parse_args()

    print("抖音带货短视频流水线")
    print(f"  项目目录: {PROJ}")
    lo = max(1, args.from_rank)
    if args.to_rank:
        hi = args.to_rank
    elif args.top:
        hi = args.top
    elif lo > 1:
        hi = 0            # 只给了起点 → 处理到榜单末尾
    else:
        hi = 10           # 什么都没指定 → 默认前 10
    if hi and hi < lo:
        lo, hi = hi, lo
    span = f"第 {lo}-{hi} 名" if hi else f"第 {lo} 名起（到末尾）"
    print(f"  榜单区间: {span}")

    # 去水印必须显式开启：用户没说「去水印」就只下载。
    do_dewm = args.dewatermark
    if args.no_clean:
        print("  · --no-clean 已废弃：现在默认就不去水印，参数保留只为兼容")
    if args.replace and not do_dewm:
        print("  ⚠ --replace 需要配合 --dewatermark，否则不生效（本次只下载）")
    if do_dewm:
        print(f"  去水印  : 执行（{args.shards} 进程并行）")
        if not args.replace:
            print("  原片处理: 保留，输出 *_去水印版.mp4（加 --replace 才删原片）")
    else:
        print("  去水印  : 跳过（默认不执行；确需去水印请加 --dewatermark）")

    # 千川规格是提交素材的硬性要求，所以默认执行；只有显式 --no-qianchuan 才跳过。
    print("  千川规格: " + ("跳过（--no-qianchuan）" if args.no_qianchuan
                            else "执行，原地统一（文件名不变）"))

    # 目录非空时提醒，避免新旧产物混在一起
    out_root = PROJ / "带货短视频"
    if out_root.exists():
        n_exist = len([p for p in out_root.rglob("*.mp4")
                       if not p.name.endswith(".part.mp4")])
        if n_exist:
            if args.clean:
                print(f"  目录清理: 将先删除现有 {n_exist} 个视频及全部子目录")
            else:
                print(f"  ⚠ 目录里已有 {n_exist} 个视频，本次下载会追加进去"
                      f"（要清空请加 --clean）")

    steps = []
    if args.clean:
        steps.append(([PY_SYS, str(SCRIPTS / "clean_output.py"), "--yes"], "⓪ 清空输出目录"))

    # ⓪.5 先把扩展加载好（不碰页面、不刷新）
    # 顺序很关键：必须在「打开页面」之前完成，新开的页面会自动注入；
    # 若放到打开页面之后修复，就不得不刷新页面，而刷新会把榜单 tab
    # 重置回「总榜」，抓取时视频数为 0。
    steps.append(([PY_SYS, str(SCRIPTS / "ensure_extension.py"), "--load"],
                  "⓪.5 确保晓风扩展已加载"))

    if not args.skip_open:
        steps.append(([PY_SYS, str(SCRIPTS / "compass_video_rank.py")], "① 打开罗盘短视频榜页面"))
    if not args.skip_fetch:
        steps.append(([PY_SYS, str(SCRIPTS / "ensure_extension.py"), "--check"],
                      "①.5 验证插件已注入（只检查，不刷新）"))
        steps.append(([PY_SYS, str(SCRIPTS / "fetch_rank.py")],
                      "② 抓取榜单商品与视频直链"))
    steps.append(([PY_SYS, str(SCRIPTS / "download_rank_videos.py"),
                   "--from", str(lo), "--to", str(hi), "--workers", str(args.workers)],
                  f"③ 下载{span}的短视频 + 商品主图（每个商品一个文件夹，文件名=文件夹名_序号）"))

    if do_dewm:
        shard_cmds = [[PY_VENV, str(SCRIPTS / "batch_run.py"),
                       "--shard", f"{i}/{args.shards}"] + (["--no-replace"] if not args.replace else [])
                      for i in range(args.shards)]
        steps.append((shard_cmds, f"④ 去水印（{args.shards} 个进程并行）"))

    # ⑤ 统一千川规格必须放在最后：它要保证最终交付的每一条都合规，
    # 放在去水印之前的话，去水印重编码有可能改变参数。
    if not args.no_qianchuan:
        steps.append(([PY_SYS, str(SCRIPTS / "qianchuan.py"), "--jobs", str(args.jobs)],
                      "⑤ 统一为巨量千川素材规格（原地覆盖，文件名不变）"))

    t0 = time.time()
    for item in steps:
        cmd, desc = item
        # 多进程步骤：同时起多个 shard
        if isinstance(cmd[0], list):
            procs = []
            for i, c in enumerate(cmd):
                print(f"\n  启动 shard {i}: {' '.join(c)}", flush=True)
                if not args.dry_run:
                    procs.append(subprocess.Popen(c, cwd=str(PROJ)))
            if args.dry_run:
                continue
            codes = [p.wait() for p in procs]
            if any(c != 0 for c in codes):
                print(f"✗ {desc} 有分片异常退出: {codes}", flush=True)
                return 1
            print(f"✓ {desc} 完成", flush=True)
        else:
            if not run(cmd, desc, dry=args.dry_run):
                return 1

    print(f"\n{'='*60}")
    print(f"流程完成，总耗时 {(time.time()-t0)/60:.1f} 分钟")
    print(f"成品目录: {PROJ / '带货短视频'}")
    # 注意：这里**不要**打印去水印的后续命令。
    # 之前这里会输出 `batch_run.py --shard 0/2`，AI 代理读到后会自动去跑去水印，
    # 而用户并没有要求去水印（一条长视频要十几分钟），属于越权执行。
    # 去水印只在用户明确要求时由人手动触发。
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
