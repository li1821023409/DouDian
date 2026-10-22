"""实验：检测宽扁的白色文字块，用"有无黑色描边"区分半透明水印与硬字幕。"""
import cv2
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE = Path(__file__).resolve().parent.parent


def find_text_blocks(frame, min_w=60, max_w=400, min_h=12, max_h=52, max_ar=20.0):
    H, W = frame.shape[:2]
    Wd = frame.min(axis=2)
    V = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    top = cv2.morphologyEx(Wd, cv2.MORPH_TOPHAT, k)
    sig = ((top > 18) & (Wd > 150)).astype(np.uint8) * 255
    # 水平连接成行
    sig = cv2.morphologyEx(sig, cv2.MORPH_CLOSE,
                           cv2.getStructuringElement(cv2.MORPH_RECT, (13, 3)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(sig, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (min_w <= w <= max_w and min_h <= h <= max_h):
            continue
        if w / max(h, 1) < 2.5 or w / max(h, 1) > max_ar:
            continue
        if area / (w * h) < 0.12:
            continue
        # 描边检测：框外 4px 环带里的暗像素比例
        px0, py0 = max(0, x - 4), max(0, y - 4)
        px1, py1 = min(W, x + w + 4), min(H, y + h + 4)
        ring = V[py0:py1, px0:px1].copy()
        inner = np.zeros(ring.shape, bool)
        inner[(y - py0):(y - py0 + h), (x - px0):(x - px0 + w)] = True
        ring_px = ring[~inner]
        dark_ratio = float((ring_px < 70).mean()) if ring_px.size else 0.0
        # 框内亮度水平
        inner_px = V[y:y + h, x:x + w]
        bright = float((inner_px > 235).mean())
        out.append(dict(box=(int(x), int(y), int(x + w), int(y + h)), w=int(w), h=int(h),
                        dark=round(dark_ratio, 3), pure_white=round(bright, 3)))
    return out


def get(name, idx):
    cap = cv2.VideoCapture(str(BASE / "input" / f"{name}.mp4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, f = cap.read()
    cap.release()
    return f if ok else None


CASES = [
    ("v1", 730, "有@水印(木地板)"),
    ("v1", 774, "有@水印"),
    ("v2", 796, "有@水印"),
    ("v2", 405, "有@水印"),
    ("v3", 479, "有@胖虎(白猫窝)"),
    ("v1", 200, "硬字幕"),
    ("v1", 500, "硬字幕"),
    ("v2", 100, "硬字幕"),
    ("v2", 620, "硬字幕"),
]

for name, idx, tag in CASES:
    f = get(name, idx)
    if f is None:
        print(f"{name}#{idx} 读取失败")
        continue
    blocks = find_text_blocks(f)
    print(f"\n{name}#{idx} [{tag}] 找到 {len(blocks)} 块")
    for b in blocks[:6]:
        print(f"   box={b['box']} {b['w']}x{b['h']} 描边暗像素={b['dark']} 纯白={b['pure_white']}")
