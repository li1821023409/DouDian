#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在各视频里扫描「左上角有白色文字行」的帧，用于定位水印并裁新模板。"""
import glob
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(r"D:\Data\DouDian\带货短视频")
OUT = Path(r"D:\Data\DouDian\video-cleaner\frames")

# 只看左上角这一带（水印常在此）
X0, Y0, X1, Y1 = 0, 0, 420, 190


def white_text_signal(roi):
    Wd = roi.min(axis=2)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    top = cv2.morphologyEx(Wd, cv2.MORPH_TOPHAT, k)
    sig = ((top > 14) & (Wd > 165)).astype(np.uint8)
    sig = cv2.morphologyEx(sig, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return int(sig.sum())


def main():
    files = [f for f in sorted(glob.glob(str(ROOT / "*" / "*.mp4")))
             if "_clean" not in os.path.basename(f)]
    results = []
    for f in files:
        cap = cv2.VideoCapture(f)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if n <= 0:
            cap.release()
            continue
        best = (0, 0)
        for i in range(0, n, max(1, n // 12)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, fr = cap.read()
            if not ok:
                continue
            roi = fr[Y0:Y1, X0:X1]
            s = white_text_signal(roi)
            if s > best[0]:
                best = (s, i)
        cap.release()
        results.append((best[0], best[1], f))
        print(f"{os.path.basename(os.path.dirname(f))[:12]:<14}{os.path.basename(f):<9}"
              f"最强信号 {best[0]:>6} @帧 {best[1]}")

    results.sort(reverse=True)
    print("\n=== 信号最强的前 3 个 ===")
    for s, idx, f in results[:3]:
        cap = cv2.VideoCapture(f)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        cap.release()
        if not ok:
            continue
        crop = fr[Y0:Y1, X0:X1]
        z = cv2.resize(crop, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_NEAREST)
        name = f"wm_candidate_{os.path.basename(os.path.dirname(f))[:6]}_{os.path.basename(f)}.png"
        cv2.imwrite(str(OUT / name), z)
        print(f"  {name}  信号 {s}  帧 {idx}  ← {os.path.relpath(f, ROOT)}")


if __name__ == "__main__":
    main()
