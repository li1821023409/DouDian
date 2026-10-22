"""裁剪并放大关注区域，用于精确读取水印像素坐标。"""
import cv2
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FRAMES = BASE / "frames"

REGIONS = [
    ("v1_f1_idx442.png", 430, 1090, 720, 1260, 3),   # 右下角水印
    ("v2_f1_idx476.png", 400, 1120, 720, 1280, 3),   # v2 右下角
]

for name, x0, y0, x1, y1, scale in REGIONS:
    img = cv2.imread(str(FRAMES / name))
    if img is None:
        print("missing", name)
        continue
    crop = img[y0:y1, x0:x1]
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    step = 20 * scale
    for gx in range(0, crop.shape[1], step):
        cv2.line(crop, (gx, 0), (gx, crop.shape[0]), (0, 255, 0), 1)
    for gy in range(0, crop.shape[0], step):
        cv2.line(crop, (0, gy), (crop.shape[1], gy), (0, 255, 0), 1)
    out = FRAMES / f"crop2_{Path(name).stem}.png"
    cv2.imwrite(str(out), crop)
    print(f"{out.name}  x[{x0},{x1}] y[{y0},{y1}] 网格20px")
