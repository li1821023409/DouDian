"""对比三种 mask 策略的修复效果：整块矩形 / 白顶帽精确笔画 / 矩形+羽化。"""
import cv2
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dewatermark import LamaOnnx, repair, mask_box_from_hit, WatermarkDetector  # noqa

BASE = Path(__file__).resolve().parent.parent
FRAMES = BASE / "frames"


def stroke_mask(frame, box, ksize=17, thresh=22, dilate=3):
    """白顶帽提取"比周围更亮的小结构"——正是半透明白色水印笔画。"""
    x0, y0, x1, y1 = box
    roi = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)
    m = (tophat > thresh).astype(np.uint8) * 255
    # 白色高亮（不管对比度如何，纯白也补上）
    mx = roi.max(axis=2).astype(np.int16)
    mn = roi.min(axis=2).astype(np.int16)
    white = ((mn > 215) & ((mx - mn) < 25)).astype(np.uint8) * 255
    m = cv2.bitwise_or(m, white)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
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
        box = mask_box_from_hit(x, y)
        x0, y0, x1, y1 = [max(0, box[0]), max(0, box[1]), min(img.shape[1], box[2]), min(img.shape[0], box[3])]
        box = (x0, y0, x1, y1)
        print(f"{fname} hit=({x},{y}) score={sc:.2f} box={box}")

        # A: 整块矩形
        mA = np.zeros(img.shape[:2], np.uint8)
        cv2.rectangle(mA, (x0, y0), (x1, y1), 255, -1)
        rA = repair(img, mA, box, backend)

        # B: 白顶帽精确笔画
        mB = stroke_mask(img, box)
        rB = repair(img, mB, box, backend)

        # C: 精确笔画 膨胀更大
        mC = stroke_mask(img, box, dilate=5)
        rC = repair(img, mC, box, backend)

        # 保存 mask 可视化 + 三种结果
        for tag, r, m in [("A", rA, mA), ("B", rB, mB), ("C", rC, mC)]:
            z = img[y0:y1, x0:x1]
            zr = r[y0:y1, x0:x1]
            zm = cv2.cvtColor(m[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
            comb = np.hstack([z, np.full((z.shape[0], 4, 3), 255, np.uint8), zm,
                              np.full((z.shape[0], 4, 3), 255, np.uint8), zr])
            comb = cv2.resize(comb, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
            out = FRAMES / f"mtest_{Path(fname).stem}_{tag}.png"
            cv2.imwrite(str(out), comb)
            print("  ", out.name)
        cv2.imwrite(str(FRAMES / f"mtest_{Path(fname).stem}_fullB.png"), rB)


if __name__ == "__main__":
    main()
