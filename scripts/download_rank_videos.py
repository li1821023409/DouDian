#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按榜单抓取结果下载带货短视频，每个商品一个文件夹（文件夹名 = 商品名）。

每个商品目录里会有：
    <商品名>_01.mp4 …         带货短视频（文件名 = 文件夹名_序号）
    <商品名>_主图.jpg/png     商品主图（榜单里那一列缩略图的原图）

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
_stat = {"ok": 0, "skip": 0, "fail": 0, "bytes": 0,
         "img_ok": 0, "img_skip": 0, "img_fail": 0}

# 商品主图后缀：`<商品名>_主图.jpg`，和视频放同一个文件夹
IMAGE_SUFFIX = "_主图"


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


def sniff_ext(path):
    """按文件头猜图片格式，返回扩展名（榜单图有 png/jpeg，别硬写 .jpg）。"""
    with open(path, "rb") as f:
        head = f.read(12)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if head[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:2] == b"BM":
        return ".bmp"
    return ".jpg"


def existing_image(folder, prefix):
    """已下载过就返回文件名（不重复下）。"""
    for ext in (".jpg", ".png", ".webp", ".bmp"):
        p = os.path.join(folder, f"{prefix}{IMAGE_SUFFIX}{ext}")
        if os.path.exists(p) and os.path.getsize(p) > 1024:
            return os.path.basename(p)
    return None


def download_image(url, folder, prefix, retries=3):
    """下载商品主图，存成 `<商品名>_主图.<真实扩展名>`。返回文件名或 None。"""
    if not url:
        return None
    have = existing_image(folder, prefix)
    if have:
        with _lk:
            _stat["img_skip"] += 1
        return have
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 1024:
                raise ValueError(f"内容异常 ({len(data)} 字节)")
            tmp = os.path.join(folder, f"{prefix}{IMAGE_SUFFIX}.part")
            with open(tmp, "wb") as f:
                f.write(data)
            name = f"{prefix}{IMAGE_SUFFIX}{sniff_ext(tmp)}"
            os.replace(tmp, os.path.join(folder, name))
            with _lk:
                _stat["img_ok"] += 1
                _stat["bytes"] += len(data)
            return name
        except Exception as e:
            if attempt == retries - 1:
                with _lk:
                    _stat["img_fail"] += 1
                print(f"  [失败] 商品图 {prefix[:18]}  {type(e).__name__}: {str(e)[:60]}",
                      flush=True)
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


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
    n_link = sum(1 for i in items for u in i["videos"]
                 if isinstance(u, str) and u.lower().startswith(("http://", "https://")))
    n_aigc = sum(len(i["videos"]) for i in items) - n_link
    print(f"榜单区间: {span}，命中 {len(items)} 个商品，"
          f"视频合计 {n_link} 个" + (f"（另 {n_aigc} 条无直链，跳过）" if n_aigc else ""))
    print(f"输出根目录: {os.path.abspath(args.out)}")
    if not items:
        print("区间内没有商品，检查 --from/--to 是否超出榜单范围")
        return

    os.makedirs(args.out, exist_ok=True)
    used, tasks, manifest = set(), [], []
    img_tasks = []
    for it in items:
        d = unique_dir(args.out, safe_name(it["title"]), used)
        os.makedirs(d, exist_ok=True)
        # 文件名 = 文件夹名 + 第几个（如 `猫窝_01.mp4`）。
        # 不叫 01.mp4 的原因：每个商品都有自己的 01~10，文件一旦离开文件夹
        # （上传、发人、拷到桌面）就分不清是哪个商品的第几条了。
        # 前缀限长 60，避免「长标题目录 + 长标题文件名」撞 260 的 MAX_PATH。
        prefix = safe_name(os.path.basename(d), maxlen=60)
        names = []
        skipped = 0
        for url in it["videos"]:
            # 兜底：JSON 可能是旧版抓的，或页面数据里混进 "aigc" 之类非 URL 标记。
            # 这些不是下载失败，直接跳过（AIGC 视频没有可直接下载的 http 直链）。
            if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
                skipped += 1
                continue
            fn = f"{prefix}_{len(names)+1:02d}.mp4"
            names.append(fn)
            tasks.append((url, os.path.join(d, fn), it, fn))
        if skipped:
            print(f"  [跳过] {it['title'][:20]} 有 {skipped} 条非直链视频"
                  f"（AIGC 生成，无 http 直链）", flush=True)
        # 商品主图：榜单里那一列缩略图，一起存进商品文件夹
        pic = (it.get("pic") or "").strip()
        if pic:
            img_tasks.append((pic, d, prefix, it))
        manifest.append({"rank": it.get("rank"), "itemid": it["itemid"],
                         "title": it["title"], "dir": os.path.basename(d),
                         "videos": len(names), "files": names,
                         "image": None,
                         "no_direct_link": skipped,
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

    # 商品主图（体积小，放在视频之后单独跑一轮）
    if img_tasks:
        print(f"\n下载商品主图：{len(img_tasks)} 张，并发 {args.workers}")
        got = {}

        def img_worker(t):
            url, folder, prefix, it = t
            name = download_image(url, folder, prefix)
            if name:
                with lock:
                    got[os.path.basename(folder)] = name
            return name

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(img_worker, img_tasks))
        for m in manifest:
            m["image"] = got.get(m["dir"])
        print(f"商品图：成功 {_stat['img_ok']}，跳过 {_stat['img_skip']}，"
              f"失败 {_stat['img_fail']}")

    mf = os.path.join(args.out, "_下载清单.json")
    json.dump({"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "items": manifest}, open(mf, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"清单: {os.path.abspath(mf)}")


if __name__ == "__main__":
    main()
