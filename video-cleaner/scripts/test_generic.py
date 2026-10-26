"""测试通用「抖音」文字模板在批量视频上的检测稳定性。"""
import cv2
import numpy as np
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = r"D:\Data\DouDian\video-cleaner"
SRC = r"D:\Data\DouDian\带货短视频"

TPL_BOX = (588, 1124, 702, 1160)   # 在 720x1280 的柏牧家视频上量出的「抖音」二字
SCALES = tuple(round(0.60 + 0.08 * i, 2) for i in range(14))  # 0.60 ~ 1.64


def build_template():
    # 模板是从某一帧里「量出来的」，不能自动猜视频，必须显式传：
    #   python test_generic.py "D:\Data\DouDian\带货短视频\<商品名>\<商品名>_01.mp4"
    if len(sys.argv) < 2:
        raise SystemExit(
            "用法: python test_generic.py <含「抖音」水印的视频路径>\n"
            "     模板要按画面固定坐标裁剪，需要指定样本视频（720x1280 才匹配 TPL_BOX）。")
    p = sys.argv[1]
    if not os.path.exists(p):
        raise SystemExit(f"文件不存在: {p}")
    cap = cv2.VideoCapture(p)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * 0.4))
    ok, f = cap.read()
    cap.release()
    x0, y0, x1, y1 = TPL_BOX
    tpl = cv2.cvtColor(f[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    cv2.imwrite(os.path.join(BASE, "models", "wm_douyin_text.png"), f[y0:y1, x0:x1])
    return tpl


def detect(frame, tpls):
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    best = (-1, 0, 0, 0, 0)
    for s, t in tpls:
        th, tw = t.shape
        if th >= g.shape[0] or tw >= g.shape[1]:
            continue
        res = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx > best[0]:
            best = (mx, loc[0], loc[1], tw, th)
    return best


def main():
    tpl0 = build_template()
    tpls = [(s, cv2.resize(tpl0, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)) for s in SCALES]
    print(f"模板 {tpl0.shape[1]}x{tpl0.shape[0]}，{len(tpls)} 个尺度\n")

    dirs = [d for d in sorted(os.listdir(SRC)) if os.path.isdir(os.path.join(SRC, d))]
    for d in dirs:
        fs = sorted(glob.glob(os.path.join(SRC, d, "*.mp4")))
        if not fs:
            continue
        cap = cv2.VideoCapture(fs[0])
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        out = []
        for frac in (0.1, 0.35, 0.6, 0.85):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * frac))
            ok, f = cap.read()
            if not ok:
                continue
            sc, x, y, w, h = detect(f, tpls)
            out.append(f"{sc:.2f}@({x},{y})")
        cap.release()
        print(f"  {d[:16]:<18} {'  '.join(out)}")


if __name__ == "__main__":
    main()
