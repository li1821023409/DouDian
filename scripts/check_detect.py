#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量检查带货短视频的水印识别情况：分辨率、检测分数、命中位置。"""
import glob
import os
import sys
from pathlib import Path

VC = Path(r"D:\Data\DouDian\video-cleaner")
sys.path.insert(0, str(VC / "scripts"))

import cv2  # noqa: E402
from dewatermark import WatermarkDetector, TPL_GENERIC  # noqa: E402

ROOT = Path(r"D:\Data\DouDian\带货短视频")


def main():
    det = WatermarkDetector(TPL_GENERIC)
    files = [f for f in sorted(glob.glob(str(ROOT / "*" / "*.mp4")))
             if "_clean" not in os.path.basename(f)]
    print(f"共 {len(files)} 个原片，阈值 0.40\n")
    print(f"{'商品':<14}{'文件':<9}{'分辨率':<14}{'分数':<8}{'位置':<14}判定")
    print("-" * 72)
    bad = []
    for f in files:
        cap = cv2.VideoCapture(f)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        scores, poss = [], []
        for frac in (0.2, 0.5, 0.8):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * frac))
            ok, fr = cap.read()
            if not ok:
                continue
            x, y, sc, s = det.detect(fr)
            scores.append(sc)
            poss.append((x, y))
        cap.release()
        if not scores:
            print(f"{os.path.basename(os.path.dirname(f))[:12]:<14}{os.path.basename(f):<9}读取失败")
            continue
        best = max(scores)
        ok = best >= 0.40
        name = os.path.basename(os.path.dirname(f))[:12]
        pos = str(poss[scores.index(best)])
        print(f"{name:<14}{os.path.basename(f):<9}{w}x{h:<9}{best:<8.2f}{pos:<14}{'OK' if ok else '✗ 未识别'}")
        if not ok:
            bad.append(f)
    print(f"\n未识别 {len(bad)} / {len(files)}")
    for b in bad:
        print("  ✗", os.path.relpath(b, ROOT))


if __name__ == "__main__":
    main()
