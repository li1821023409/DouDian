#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按榜单抓取结果下载带货短视频，每个商品一个文件夹（文件夹名 = 商品名）。

用法：
    python download_rank_videos.py                 # 下载全部
    python download_rank_videos.py --limit 3       # 只下前 3 个商品（试跑）
    python download_rank_videos.py --workers 8     # 并发数
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_here = os.path.dirname(os.path.abspath(__file__))
RANK_JSON = os.path.join(_here, "..", "商品数据", "短视频榜单_抓取.json")
OUT_ROOT = os.path.join(_here, "..", "带货短视频")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://compass.jinritemai.com/", "Accept": "*/*"}

_lk = threading.Lock()
_stat = {"ok": 0, "skip": 0, "fail": 0, "bytes": 0}


def safe_name(title, maxlen=70):
    """清洗成合法 Windows 目录名。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", title or "")
    s = re.sub(r"\s+", " ", s).strip(" .")
    # 去掉连续下划线/空格
    s = re.sub(r"[_ ]{2,}", "_", s)
    if len(s) > maxlen:
        s = s[:maxlen].rstrip(" ._")
    return s or "未命名商品"


def unique_dir(root, name, used):
    with _lk:
        base = name
        i = 2
        while base in used or os.path.exists(os.path.join(root, base)):
            base = f"{name}_{i}"
            i += 1
        used.add(base)
        return os.path.join(root, base)


def download_one(url, dest, retries=3):
    if os.path.exists(dest) and os.path.getsize(dest) > 10240:
        with _lk:
            _stat["skip"] += 1
        return True, "exists"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 10240 or not data[4:8] == b"ftyp":
                raise ValueError(f"内容异常 ({len(data)} 字节)")
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            with _lk:
                _stat["ok"] += 1
                _stat["bytes"] += len(data)
            return True, f"{len(data)/1e6:.1f}MB"
        except Exception as e:
            if attempt == retries - 1:
                with _lk:
                    _stat["fail"] += 1
                return False, f"{type(e).__name__}: {str(e)[:80]}"
            time.sleep(1.5 * (attempt + 1))
    return False, "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个商品（兼容旧用法，等价 --to N）")
    ap.add_argument("--from", dest="from_rank", type=int, default=1,
                    help="起始排名（含），从 1 开始。例：10")
    ap.add_argument("--to", dest="to_rank", type=int, default=0,
                    help="结束排名（含）。0 表示到最后。例：15")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=OUT_ROOT)
    args = ap.parse_args()

    data = json.load(open(RANK_JSON, encoding="utf-8"))
    all_items = data["items"]

    lo = max(1, args.from_rank)
    hi = args.to_rank or args.limit or len(all_items)
    if hi < lo:
        lo, hi = hi, lo
    items = [it for it in all_items if lo <= (it.get("rank") or 0) <= hi]

    span = f"{lo}-{hi}" if hi < len(all_items) else f"{lo} 名起（共 {len(all_items)} 名）"
    print(f"榜单区间: {span}，命中 {len(items)} 个商品，"
          f"视频合计 {sum(len(i['videos']) for i in items)} 个")
    print(f"输出根目录: {os.path.abspath(args.out)}")
    if not items:
        print("区间内没有商品，检查 --from/--to 是否超出榜单范围")
        return

    os.makedirs(args.out, exist_ok=True)
    used, tasks, manifest = set(), [], []
    for it in items:
        d = unique_dir(args.out, safe_name(it["title"]), used)
        os.makedirs(d, exist_ok=True)
        names = []
        for k, url in enumerate(it["videos"], 1):
            fn = f"{k:02d}.mp4"
            names.append(fn)
            tasks.append((url, os.path.join(d, fn), it, fn))
        manifest.append({"rank": it.get("rank"), "itemid": it["itemid"],
                         "title": it["title"], "dir": os.path.basename(d),
                         "videos": len(it["videos"]), "files": names,
                         "price": it.get("price"), "label": it.get("label")})

    print(f"共 {len(tasks)} 个视频待下载，并发 {args.workers}\n")
    t0 = time.time()
    done = 0
    lock = threading.Lock()

    def worker(t):
        nonlocal done
        url, dest, it, fn = t
        ok, msg = download_one(url, dest)
        with lock:
            done += 1
            if not ok:
                print(f"  [失败] {it['title'][:20]} / {fn}  {msg}", flush=True)
            elif done % 20 == 0 or done == len(tasks):
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (len(tasks) - done) / rate if rate else 0
                print(f"  进度 {done}/{len(tasks)}  成功{_stat['ok']} 跳过{_stat['skip']} "
                      f"失败{_stat['fail']}  {_stat['bytes']/1e6:.0f}MB  "
                      f"{rate:.1f}个/s  剩余{eta:.0f}s", flush=True)
        return ok

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(worker, tasks))

    el = time.time() - t0
    print(f"\n完成：成功 {_stat['ok']}，跳过 {_stat['skip']}，失败 {_stat['fail']}，"
          f"共 {_stat['bytes']/1e6:.0f} MB，用时 {el:.0f}s")

    mf = os.path.join(args.out, "_下载清单.json")
    json.dump({"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "items": manifest}, open(mf, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"清单: {os.path.abspath(mf)}")


if __name__ == "__main__":
    main()
