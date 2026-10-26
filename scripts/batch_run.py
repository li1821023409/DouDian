#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量去水印执行器：支持分片并行、断点续跑、失败隔离。

每个视频处理成功后，用无水印版原地替换原文件，并记录到进度 JSON。

用法：
    python batch_run.py --shard 0/2       # 两个进程并行时用 0/2 和 1/2
    python batch_run.py --shard 0/2 --limit 5   # 只跑前 5 个（试跑）
"""
import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # D:\Data\DouDian\scripts
PROJ = HERE.parent                              # D:\Data\DouDian
VC = PROJ / "video-cleaner"
sys.path.insert(0, str(VC / "scripts"))

from dewatermark import (  # noqa: E402
    LamaTorch, process_video, TPL_GENERIC, EXPAND_GENERIC, _probe_duration,
)

ROOT = PROJ / "带货短视频"
PROGRESS = ROOT / "_去水印进度.json"


def sweep_broken(root: Path, suffix: str):
    """清掉上次中断留下的半成品。

    两种都要清：
      · `*.part.mp4`  —— 写到一半的中间产物（正常结束会改名成正式文件名）
      · `*_去水印版.mp4` 但 moov 缺失 —— 旧版本直接写最终文件名时被中断的产物，
        Windows 里没缩略图、放不了，留着只会被当成成品混过去。
    """
    n_part = n_bad = 0
    for p in root.glob("*/*.part.mp4"):
        try:
            p.unlink()
            n_part += 1
        except OSError:
            pass
    for p in root.glob(f"*/*{suffix}.mp4"):
        if not _probe_duration(p):
            try:
                p.unlink()
                n_bad += 1
                print(f"  [清理] 删除无效成品 {p.parent.name}\\{p.name}（缺 moov，无法播放）",
                      flush=True)
            except OSError:
                pass
    if n_part or n_bad:
        print(f"  [清理] 中间产物 {n_part} 个，无效成品 {n_bad} 个", flush=True)


def load_progress():
    if PROGRESS.exists():
        try:
            return json.load(open(PROGRESS, encoding="utf-8"))
        except Exception:
            pass
    return {"done": {}, "failed": {}}


def save_progress(p):
    tmp = PROGRESS.with_suffix(".tmp")
    json.dump(p, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, PROGRESS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default="0/1", help="i/n，按索引取模分片")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--no-replace", action="store_true",
                    help="只输出去水印版，不替换原片")
    ap.add_argument("--out-suffix", default="_去水印版", help="去水印成品后缀")
    args = ap.parse_args()

    i, n = (int(x) for x in args.shard.split("/"))
    sweep_broken(ROOT, args.out_suffix)
    files = sorted(str(p) for p in ROOT.glob("*/*.mp4")
                   if args.out_suffix not in p.stem and "_clean" not in p.stem)
    mine = [f for k, f in enumerate(files) if k % n == i]
    if args.limit:
        mine = mine[:args.limit]

    prog = load_progress()
    todo = [f for f in mine if os.path.relpath(f, ROOT) not in prog["done"]]
    print(f"[shard {i}/{n}] 分到 {len(mine)} 条，已完成 {len(mine)-len(todo)}，待处理 {len(todo)}",
          flush=True)
    if not todo:
        return

    backend = LamaTorch("cuda")
    print(f"后端 {backend.name}", flush=True)

    t0 = time.time()
    ok = bad = 0
    for k, f in enumerate(todo, 1):
        rel = os.path.relpath(f, ROOT)
        print(f"\n[{i}/{n}] {k}/{len(todo)}  {rel}", flush=True)
        try:
            r = process_video(
                Path(f), Path(f).parent, backend,
                template=TPL_GENERIC, expand=EXPAND_GENERIC,
                detect_at=False, detect_interval=args.interval,
                replace=not args.no_replace, use_refine=False,
                out_suffix=args.out_suffix,
            )
        except Exception as e:
            print(f"  [异常] {type(e).__name__}: {e}", flush=True)
            r = None
        if r:
            prog["done"][rel] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                 "size": os.path.getsize(f)}
            ok += 1
        else:
            prog["failed"][rel] = {"at": time.strftime("%Y-%m-%d %H:%M:%S")}
            bad += 1
        save_progress(prog)
        el = time.time() - t0
        print(f"  进度 {ok+bad}/{len(todo)}  成功{ok} 失败{bad}  已用 {el/60:.1f} 分钟", flush=True)

    print(f"\n[shard {i}/{n}] 完成：成功 {ok}，失败 {bad}，用时 {(time.time()-t0)/60:.1f} 分钟", flush=True)


if __name__ == "__main__":
    main()
