"""扫描画面中各"半透明白色文字"候选带，找出模板检测漏掉的水印。"""
import cv2
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dewatermark import WatermarkDetector  # noqa

BASE = Path(__file__).resolve().parent.parent
INPUT = BASE / "input"

# 候选带（按 720x1280 设计，按比例缩放）
ZONES = {
    "左上": (0.00, 0.00, 0.50, 0.16),
    "右上": (0.50, 0.00, 1.00, 0.16),
    "左中": (0.00, 0.16, 0.50, 0.55),
    "右中": (0.50, 0.16, 1.00, 0.55),
    "左下": (0.00, 0.62, 0.50, 0.90),
    "右下": (0.50, 0.62, 1.00, 0.90),
}


def zone_signal(frame, rect):
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = [int(rect[0] * W), int(rect[1] * H), int(rect[2] * W), int(rect[3] * H)]
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0
    Wd = roi.min(axis=2)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    top = cv2.morphologyEx(Wd, cv2.MORPH_TOPHAT, k)
    sig = ((top > 22) & (Wd > 145)).astype(np.uint8)
    # 形态学过滤掉细碎噪点，只保留文字笔画级别的连通块
    sig = cv2.morphologyEx(sig, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return float(sig.sum()) / (roi.shape[0] * roi.shape[1]) * 1000


for name in ["v1", "v2", "v3"]:
    p = INPUT / f"{name}.mp4"
    cap = cv2.VideoCapture(str(p))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    step = max(1, int(fps / 4))
    det = WatermarkDetector()
    rows = []
    for i in range(0, n, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            break
        x, y, sc, s = det.detect(fr)
        vals = {z: zone_signal(fr, r) for z, r in ZONES.items()}
        rows.append((i, (x, y), sc, vals))
    cap.release()

    print(f"\n===== {name}  ({n} 帧, 采样 {len(rows)}) =====")
    for z in ZONES:
        arr = np.array([r[3][z] for r in rows])
        if arr.max() < 1.0:
            continue
        # 找出信号显著高于基线的时段
        base = np.median(arr)
        hot = [(rows[i][0], round(arr[i], 2)) for i in range(len(arr)) if arr[i] > max(base * 2.2, 1.2)]
        print(f"  [{z}] 基线={base:.2f} 峰值={arr.max():.2f}  异常帧 {len(hot)} 个")
        if hot:
            print(f"       帧号: {[h[0] for h in hot[:14]]}{' ...' if len(hot) > 14 else ''}")
