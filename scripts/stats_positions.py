#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计一个视频里水印命中的全部位置及帧数占比，用来看是否漏掉了某些位置。"""
import sys
from collections import Counter
from pathlib import Path

VC = Path(r"D:\Data\DouDian\video-cleaner")
sys.path.insert(0, str(VC / "scripts"))

import cv2  # noqa: E402
from dewatermark import WatermarkDetector, TPL_GENERIC  # noqa: E402

ROOT = Path(r"D:\Data\DouDian\带货短视频")
# 默认样本：文件名 = 文件夹名 + 序号（见 download_rank_videos.py）
SAMPLE_DIR = "萌仆内外同驱猫狗驱虫吡虫啉莫昔克丁寄生虫体内外一体驱无需喂药"
SRC = (sys.argv[1] if len(sys.argv) > 1
       else str(ROOT / SAMPLE_DIR / f"{SAMPLE_DIR}_08.mp4"))
STEP = 15


def main():
    det = WatermarkDetector(TPL_GENERIC)
    cap = cv2.VideoCapture(SRC)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"{Path(SRC).name}  {W}x{H}  {n} 帧，每 {STEP} 帧采样")
    print(f"阈值 {det.thresh}\n")

    cnt = Counter()
    hits = 0
    total = 0
    for i in range(0, n, STEP):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            continue
        total += 1
        x, y, sc, s = det.detect(fr)
        if sc >= det.thresh:
            hits += 1
            cnt[(x // 12 * 12, y // 12 * 12)] += 1
    cap.release()

    print(f"命中 {hits}/{total} 次采样\n")
    print(f"{'位置':<16}{'采样数':<8}{'占比':<8}遮罩框")
    for (x, y), c in cnt.most_common(20):
        pct = c / max(total, 1) * 100
        box = (max(0, x + 8), max(0, y - 18), min(W, x + 126 + 165), min(H, y + 34 + 112))
        print(f"({x:>4},{y:>4})    {c:<8}{pct:>5.1f}%   {box}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
