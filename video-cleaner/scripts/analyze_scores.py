"""统计三个视频的水印检测分数分布，用于确定阈值与位置分段。"""
import cv2
import numpy as np
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dewatermark import WatermarkDetector  # noqa

BASE = Path(__file__).resolve().parent.parent

for name in ["v1", "v2", "v3"]:
    p = BASE / "input" / f"{name}.mp4"
    cap = cv2.VideoCapture(str(p))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    det = WatermarkDetector()
    scores, poss = [], []
    step = max(1, int(fps / 2))  # 每 0.5 秒采一帧
    for i in range(0, n, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            break
        x, y, sc, s = det.detect(fr)
        scores.append(sc)
        poss.append((x, y))
    cap.release()
    s = np.array(scores)
    print(f"\n{name}: {n} 帧 @{fps:.1f}fps  采样 {len(s)} 帧")
    print(f"  分数 min={s.min():.2f} p10={np.percentile(s,10):.2f} "
          f"中位={np.median(s):.2f} p90={np.percentile(s,90):.2f} max={s.max():.2f}")
    for lo, hi in [(0, .2), (.2, .3), (.3, .4), (.4, .6), (.6, 1.01)]:
        c = int(((s >= lo) & (s < hi)).sum())
        print(f"  [{lo:.1f},{hi:.1f}) : {c}")
    print("  位置分布:", Counter(poss).most_common(5))
    # 位置随时间变化
    changes = [i for i in range(1, len(poss)) if poss[i] != poss[i - 1]]
    print(f"  位置切换点（采样序号）: {changes[:10]}")
