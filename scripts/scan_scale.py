#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""尺度扫描：看「抖音号：」模板在多大缩放下才能匹配到这些视频的真实水印位置。"""
import sys
from pathlib import Path

VC = Path(r"D:\Data\DouDian\video-cleaner")
sys.path.insert(0, str(VC / "scripts"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

TPL = cv2.imread(str(VC / "models" / "wm_douyinvhao.png"))
BASE = TPL.min(axis=2).astype(np.float32)
ROOT = Path(r"D:\Data\DouDian\带货短视频")

CASES = [
    ("【潘宏同款】增肌壮骨犬粮全新升级版全犬种通用狗粮增肌壮骨狗粮", "04.mp4", "未识别"),
    ("【潘宏同款】增肌壮骨犬粮全新升级版全犬种通用狗粮增肌壮骨狗粮", "01.mp4", "低分误检"),
    ("【潘宏同款】美伊天祺全价鲜肉乳鸽猫粮", "01.mp4", "未识别"),
    ("【潘宏同款】美伊天祺全价鲜肉乳鸽猫粮", "07.mp4", "已知OK(0.89)"),
]

SCALES = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.10, 1.20]


def main():
    print("模板", BASE.shape, "尺度候选", SCALES, "\n")
    for d, fn, tag in CASES:
        p = ROOT / d / fn
        if not p.exists():
            print("跳过", p)
            continue
        cap = cv2.VideoCapture(str(p))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * 0.5))
        ok, fr = cap.read()
        cap.release()
        if not ok:
            continue
        Wd = fr.min(axis=2).astype(np.float32)
        print(f"--- {d[:14]} {fn} [{tag}] {fr.shape[1]}x{fr.shape[0]}")
        best_overall = (0, None, None)
        for s in SCALES:
            t = cv2.resize(BASE, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            th, tw = t.shape
            if th >= Wd.shape[0] or tw >= Wd.shape[1]:
                continue
            res = cv2.matchTemplate(Wd, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            mark = ""
            if mx > best_overall[0]:
                best_overall = (mx, s, loc)
            if mx > 0.55:
                mark = " <<<"
            print(f"   s={s:.2f} 尺寸{tw}x{th} 分数{mx:.3f} @{loc}{mark}")
        print(f"   >>> 最佳: {best_overall[0]:.3f} (尺度 {best_overall[1]}) @{best_overall[2]}\n")


if __name__ == "__main__":
    main()
