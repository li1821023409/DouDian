"""对比 mask 策略 v2：白度图 + 白顶帽，只对半透明白色水印响应。"""
import cv2
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dewatermark import LamaOnnx, repair, mask_box_from_hit, WatermarkDetector  # noqa

BASE = Path(__file__).resolve().parent.parent
FRAMES = BASE / "frames"


def stroke_mask(frame, box, ksize=25, thresh=18, min_w=130, dilate=3):
    x0, y0, x1, y1 = box
    roi = frame[y0:y1, x0:x1]
    W = roi.min(axis=2)                      # 白度：白色水印高，彩色/暗背景低
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    tophat = cv2.morphologyEx(W, cv2.MORPH_TOPHAT, k)
    m = ((tophat > thresh) & (W > min_w)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    if dilate:
        m = cv2.dilate(m, np.ones((dilate, dilate), np.uint8))
    out = np.zeros(frame.shape[:2], np.uint8)
    out[y0:y1, x0:x1] = m
    return out


def main():
    backend = LamaOnnx("CPU")
    det = WatermarkDetector()

    for fname in ["v1_f0_idx44.png", "v1_f1_idx442.png"]:
        img = cv2.imread(str(FRAMES / fname))
        x, y, sc, s = det.detect(img)
        x0, y0, x1, y1 = mask_box_from_hit(x, y)
        box = (max(0, x0), max(0, y0), min(img.shape[1], x1), min(img.shape[0], y1))
        print(f"{fname} hit=({x},{y}) score={sc:.2f}")

        variants = {
            "D": stroke_mask(img, box, ksize=25, thresh=18, min_w=130, dilate=3),
            "E": stroke_mask(img, box, ksize=31, thresh=14, min_w=120, dilate=4),
            "F": stroke_mask(img, box, ksize=21, thresh=22, min_w=140, dilate=5),
        }
        for tag, m in variants.items():
            r = repair(img, m, box, backend)
            ax0, ay0, ax1, ay1 = box
            z = img[ay0:ay1, ax0:ax1]
            zm = cv2.cvtColor(m[ay0:ay1, ax0:ax1], cv2.COLOR_GRAY2BGR)
            zr = r[ay0:ay1, ax0:ax1]
            comb = np.hstack([z, np.full((z.shape[0], 4, 3), 255, np.uint8), zm,
                              np.full((z.shape[0], 4, 3), 255, np.uint8), zr])
            comb = cv2.resize(comb, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
            cv2.imwrite(str(FRAMES / f"m2_{Path(fname).stem}_{tag}.png"), comb)
            print("  ", f"m2_{Path(fname).stem}_{tag}.png")


if __name__ == "__main__":
    main()
