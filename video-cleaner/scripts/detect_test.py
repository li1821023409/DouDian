"""实验：用白度图 + 模板匹配逐帧定位抖音水印，输出检测分数与可视化拼图。"""
import cv2
import numpy as np
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FRAMES = BASE / "frames"

# 从 v1_f1 右下角裁出的 "抖音号: nimo520520" 文字行（含边缘留白）
TPL_BOX = (448, 1182, 714, 1220)


def whiteness(bgr):
    """水印是半透明白色叠加，min(R,G,B) 对白色响应最强。"""
    return bgr.min(axis=2)


def build_template():
    img = cv2.imread(str(FRAMES / "v1_f1_idx442.png"))
    x0, y0, x1, y1 = TPL_BOX
    tpl = whiteness(img[y0:y1, x0:x1])
    return tpl


def detect(frame, tpl, thresh=0.45):
    w = whiteness(frame)
    res = cv2.matchTemplate(w, tpl, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    return maxloc, maxv


def main():
    tpl = build_template()
    th, tw = tpl.shape
    print(f"模板 {tw}x{th}")

    for name in ["v1", "v2", "v3"]:
        cap = cv2.VideoCapture(str(BASE / "input" / f"{name}.mp4"))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        thumbs = []
        for i in range(12):
            idx = int(n * (i + 0.5) / 12)
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, fr = cap.read()
            if not ok:
                continue
            loc, score = detect(fr, tpl)
            vis = fr.copy()
            cv2.rectangle(vis, loc, (loc[0] + tw, loc[1] + th), (0, 0, 255), 2)
            cv2.putText(vis, f"{score:.2f}", (loc[0], max(loc[1] - 6, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
            small = cv2.resize(vis, (240, 427), interpolation=cv2.INTER_AREA)
            cv2.putText(small, f"#{idx} {score:.2f}", (5, 18), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 255), 1, cv2.LINE_AA)
            thumbs.append(small)
            print(f"  {name} idx={idx:4d} score={score:.3f} loc={loc}")
        cap.release()

        rows, cols = 3, 4
        h, w = thumbs[0].shape[:2]
        canvas = np.zeros((h * rows, w * cols, 3), np.uint8)
        for k, t in enumerate(thumbs[:rows * cols]):
            r, c = divmod(k, cols)
            canvas[r * h:(r + 1) * h, c * w:(c + 1) * w] = t
        cv2.imwrite(str(FRAMES / f"detect_{name}.png"), canvas)


if __name__ == "__main__":
    main()
