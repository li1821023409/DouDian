#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抖音带货短视频 · 全流程流水线

    打开罗盘短视频榜 → 抓榜单直链 → 按商品分文件夹下载 → 批量去水印

用法：
    python scripts/run_pipeline.py --top 10                  # 完整跑：1-10 名，下载后自动去水印
    python scripts/run_pipeline.py --top 10 --no-clean       # 只下载，不去水印
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
    ap = argparse.ArgumentParser(description="抖音带货短视频全流程：榜单→下载→去水印")
    ap.add_argument("--from", dest="from_rank", type=int, default=1,
                    help="起始排名（含），从 1 开始。例：--from 10")
    ap.add_argument("--to", dest="to_rank", type=int, default=0,
                    help="结束排名（含）。例：--to 15")
    ap.add_argument("--top", type=int, default=0,
                    help="等价于 --to（只下前 N 名，默认 10）")
    ap.add_argument("--skip-open", action="store_true", help="跳过打开榜单页")
    ap.add_argument("--skip-fetch", action="store_true", help="跳过抓取，复用已有 JSON")
    ap.add_argument("--no-clean", action="store_true", help="只下载，不去水印")
    ap.add_argument("--replace", action="store_true", help="去水印成功后删除原片（默认保留）")
    ap.add_argument("--workers", type=int, default=6, help="下载并发")
    ap.add_argument("--shards", type=int, default=2, help="去水印并行进程数")
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
    print(f"  去水印  : {'跳过' if args.no_clean else f'执行（{args.shards} 进程并行）'}")
    if not args.no_clean and not args.replace:
        print("  原片处理: 保留，输出 *_clean.mp4（加 --replace 才删原片）")

    # 目录非空时提醒，避免新旧产物混在一起
    out_root = PROJ / "带货短视频"
    if out_root.exists():
        n_exist = len([p for p in out_root.rglob("*.mp4")])
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
                  f"③ 下载{span}的短视频（按商品名建文件夹）"))

    if not args.no_clean:
        shard_cmds = [[PY_VENV, str(SCRIPTS / "batch_run.py"),
                       "--shard", f"{i}/{args.shards}"] + (["--no-replace"] if not args.replace else [])
                      for i in range(args.shards)]
        steps.append((shard_cmds, f"④ 去水印（{args.shards} 个进程并行）"))

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
    print(f"全流程完成，总耗时 {(time.time()-t0)/60:.1f} 分钟")
    print(f"成品目录: {PROJ / '带货短视频'}")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
