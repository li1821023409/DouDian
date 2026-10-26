#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清空「带货短视频」目录 —— 批量删除下载产物（含子文件夹）

默认 **只预览不删除**，确认后加 --yes 才真正执行。

用法：
    python scripts/clean_output.py                # 预览：列出将删除的内容
    python scripts/clean_output.py --yes          # 真正删除
    python scripts/clean_output.py --yes --keep-clean       # 只删原片，保留去水印版 / 千川版
    python scripts/clean_output.py --yes --keep "_下载清单.json" "_榜单对照_1-10.md"
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from video_rules import is_derived  # noqa: E402

DEFAULT_ROOT = Path(r"D:\Data\DouDian\带货短视频")
# 护栏：这几个目录绝不允许被当作清理目标
FORBIDDEN = {
    Path("D:/"), Path("D:\\"),
    Path(r"D:\Data"),
    Path(r"D:\Data\DouDian"),
    Path.home(),
}


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f}{u}" if u != "B" else f"{int(n)}B"
        n /= 1024


def is_clean_file(p: Path) -> bool:
    """是否为流水线成品（去水印版 / 千川版，兼容旧的 _clean）。

    --keep-clean 靠它区分「原片」和「成品」。新增派生后缀时改
    video_rules.DERIVED_SUFFIXES，不要在这里加判断。
    """
    return is_derived(p)


def collect(root: Path, keep_names, keep_clean):
    """返回 (待删文件列表, 待删目录列表, 保留文件列表)。"""
    files, dirs, kept = [], [], []
    for entry in sorted(root.iterdir()):
        name = entry.name
        if name in keep_names:
            kept.append(entry)
            continue
        if entry.is_dir():
            inner = [p for p in entry.rglob("*") if p.is_file()]
            hit = [p for p in inner if not (keep_clean and is_clean_file(p))]
            if keep_clean and len(hit) < len(inner):
                # 目录里既有原片又有成品：只删原片，目录保留
                files.extend(hit)
                kept.extend([p for p in inner if p not in hit])
            else:
                dirs.append(entry)
            continue
        if keep_clean and is_clean_file(entry):
            kept.append(entry)
            continue
        files.append(entry)
    return files, dirs, kept


def main():
    ap = argparse.ArgumentParser(description="清空带货短视频目录（默认只预览）")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--yes", action="store_true", help="确认执行删除")
    ap.add_argument("--keep", nargs="*", default=[], help="要保留的文件名（精确匹配）")
    ap.add_argument("--keep-clean", action="store_true", help="保留 *_clean.mp4")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    print(f"目标目录: {root}")

    # ---- 安全护栏 ----
    if not root.exists():
        print("✗ 目录不存在")
        return 1
    if not root.is_dir():
        print("✗ 目标不是目录")
        return 1
    if root in FORBIDDEN or len(root.parts) <= 3:
        print(f"✗ 拒绝执行：{root} 属于危险路径（盘符根或项目根）")
        return 2
    if root.name != "带货短视频" and "--root" not in " ".join(sys.argv):
        print(f"✗ 拒绝执行：目录名不是「带货短视频」。确需指定其它目录请显式传 --root")
        return 2

    keep = set(args.keep or [])
    files, dirs, kept = collect(root, keep, args.keep_clean)

    total = sum(p.stat().st_size for p in files if p.exists())
    for d in dirs:
        total += sum(p.stat().st_size for p in d.rglob("*") if p.is_file())

    print(f"\n{'='*58}")
    print(f"  待删除： {len(files)} 个散落文件 + {len(dirs)} 个商品文件夹")
    print(f"  总大小： {human(total)}")
    if kept:
        print(f"  将保留： {len(kept)} 个（{'保留 _clean' if args.keep_clean else '按 --keep 指定'}）")
    print(f"{'='*58}")

    if dirs:
        print("\n商品文件夹：")
        for d in dirs:
            n = len([p for p in d.rglob("*") if p.is_file()])
            sz = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
            print(f"  - {d.name[:46]:<48} {n:>3} 个文件  {human(sz)}")
    if files:
        print("\n散落文件：")
        for f in files[:15]:
            print(f"  - {f.name}  {human(f.stat().st_size)}")
        if len(files) > 15:
            print(f"  ... 另有 {len(files)-15} 个")

    if not args.yes:
        print(f"\n这是预览。确认无误后执行：")
        print(f"  python scripts/clean_output.py --yes")
        return 0

    # ---- 执行 ----
    print("\n开始删除 ...")
    t0 = time.time()
    ok = fail = 0
    errs = []
    for d in dirs:
        try:
            shutil.rmtree(d)
            ok += 1
        except Exception as e:
            fail += 1
            errs.append(f"{d.name}: {e}")
    for f in files:
        try:
            f.unlink()
            ok += 1
        except Exception as e:
            fail += 1
            errs.append(f"{f.name}: {e}")

    left = [p for p in root.iterdir()]
    print(f"\n完成：删除 {ok} 项，失败 {fail} 项，用时 {time.time()-t0:.1f}s")
    print(f"目录剩余条目：{len(left)} 个" + (f"（{'、'.join(p.name for p in left[:5])}）" if left else "（已清空）"))
    if errs:
        print("\n失败明细：")
        for e in errs[:10]:
            print("  !", e)
    return 0 if fail == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
