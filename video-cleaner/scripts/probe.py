"""提取视频基本信息并抽帧，用于肉眼定位水印位置。"""
import cv2
import sys
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INPUT = BASE / "input"
FRAMES = BASE / "frames"
FRAMES.mkdir(exist_ok=True)


def probe(path: Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        print(f"[FAIL] 打不开 {path}")
        return None
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    dur = n / fps if fps else 0
    print(f"{path.name}: {w}x{h}  fps={fps:.2f}  frames={n}  duration={dur:.2f}s")

    # 均匀取 3 帧
    picks = [int(n * r) for r in (0.05, 0.5, 0.92)]
    for i, idx in enumerate(picks):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if ok:
            out = FRAMES / f"{path.stem}_f{i}_idx{idx}.png"
            cv2.imwrite(str(out), frame)
            print(f"  -> {out.name}")
    cap.release()
    return dict(w=w, h=h, fps=fps, n=n, dur=dur)


if __name__ == "__main__":
    for f in sorted(INPUT.glob("*.mp4")):
        probe(f)
