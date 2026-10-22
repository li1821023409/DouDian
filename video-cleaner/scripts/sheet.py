"""生成联系表（contact sheet），用于观察水印在整段视频中的位置变化规律。"""
import cv2
import numpy as np
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INPUT = BASE / "input"
FRAMES = BASE / "frames"

COLS, ROWS = 4, 3
THUMB_W = 240


def sheet(path: Path, out: Path, count=12):
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    thumbs = []
    for i in range(count):
        idx = int(n * (i + 0.5) / count)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        if not ok:
            continue
        h, w = fr.shape[:2]
        tw = THUMB_W
        th = int(h * tw / w)
        small = cv2.resize(fr, (tw, th), interpolation=cv2.INTER_AREA)
        # 标注帧号
        cv2.putText(small, f"#{idx}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 0, 255), 2, cv2.LINE_AA)
        thumbs.append(small)
    cap.release()

    if not thumbs:
        return
    th = thumbs[0].shape[0]
    canvas = np.zeros((th * ROWS, THUMB_W * COLS, 3), np.uint8)
    for i, t in enumerate(thumbs[:COLS * ROWS]):
        r, c = divmod(i, COLS)
        canvas[r * th:(r + 1) * th, c * THUMB_W:(c + 1) * THUMB_W] = t
    cv2.imwrite(str(out), canvas)
    print("saved", out)


if __name__ == "__main__":
    for f in sorted(INPUT.glob("*.mp4")):
        sheet(f, FRAMES / f"sheet_{f.stem}.png")
