#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
抖音/TikTok 短视频水印清除 —— 主流程

流程：逐帧模板匹配定位水印 -> 生成 mask -> LaMa 修复 -> 无损中间件 -> ffmpeg 合成音轨

用法：
    python dewatermark.py -i input/v1.mp4 -o output
    python dewatermark.py -i input -o output            # 处理整个目录
    python dewatermark.py -i input/v1.mp4 --limit 60    # 只处理前 60 帧（试跑）
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent.parent
MODEL_ONNX = BASE / "models" / "lama_fp32.onnx"
MODEL_PT = BASE / "models" / "big-lama.pt"
TEMPLATE = BASE / "models" / "wm_template.png"
# 跨账号通用模板：「抖音号：」四字（所有抖音分享视频都有，且不会出现在商品包装/促销文案里）
TPL_GENERIC = BASE / "models" / "wm_douyinvhao.png"
FFMPEG = BASE / "tools" / "ffmpeg-master-latest-win64-gpl" / "bin" / "ffmpeg.exe"

# 模板是"抖音号：xxx"文字行的小图（266x38），MASK_EXPAND 是它到整块水印的偏移
MASK_EXPAND = (-12, -92, 12, 56)
# 通用模板是「抖音号：」（126x34），整块水印相对它的偏移
EXPAND_GENERIC = (8, -50, 165, 112)
WIN = 512
# 去水印成品的文件名后缀
DEFAULT_SUFFIX = "_去水印版"
LEGACY_SUFFIX = "_clean"


# ---------------------------------------------------------------- 检测
def corner_hit(x, y, W, H):
    """水印只出现在画面四角。画面中部的命中基本都是误检（手指、衣料、随机文字），
    实测阈值 0.4 时 31 个视频里有 21 个是这种误检，会把画面中间乱修一通。"""
    near_top = y < H * 0.30
    near_bottom = y > H * 0.55
    near_left = x < W * 0.30
    near_right = x > W * 0.45
    return (near_top or near_bottom) and (near_left or near_right)


class WatermarkDetector:
    """白度图 + 多尺度模板匹配。抖音水印是半透明白色叠加，min(R,G,B) 响应最强。"""

    SCALES = (0.86, 0.90, 0.94, 0.97, 1.0, 1.03, 1.06, 1.10, 1.14)

    def __init__(self, template_path=TEMPLATE, thresh=0.62):
        img = cv2.imread(str(template_path))
        if img is None:
            raise FileNotFoundError(f"模板图不存在: {template_path}")
        tpl = img.min(axis=2)
        self.templates = []
        for s in self.SCALES:
            t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            self.templates.append((s, t))
        self.base_h, self.base_w = tpl.shape
        self.thresh = thresh
        self.scores = []

    def _verify(self, frame, x, y, w, h):
        """真水印的「抖音」二字下方紧跟「抖音号：xxx」白字行；画面里的其它中文没有这层结构。"""
        H, W = frame.shape[:2]
        ry0, ry1 = y + h + 4, min(H, y + h + 52)
        rx0, rx1 = max(0, x - 170), min(W, x + 210)
        if ry1 - ry0 < 12 or rx1 - rx0 < 40:
            return False
        roi = frame[ry0:ry1, rx0:rx1]
        Wd = roi.min(axis=2)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        top = cv2.morphologyEx(Wd, cv2.MORPH_TOPHAT, k)
        ratio = float(((top > 12) & (Wd > 140)).mean())
        return ratio > 0.045

    def detect(self, frame):
        """返回 (x, y, score, scale)；x,y 为 1.0 尺度下的文字行左上角坐标。"""
        w = frame.min(axis=2)
        best = (-1.0, 0, 0, 1.0)
        for s, t in self.templates:
            res = cv2.matchTemplate(w, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx > best[0]:
                # 把缩放尺度下的坐标折算回基准尺度
                bx = int(round(loc[0] / s))
                by = int(round(loc[1] / s))
                best = (mx, bx, by, s)
        score, x, y, s = best
        if score < self.thresh:
            self.scores.append(score)
            return x, y, score, s
        # 位置不对（画面中部）→ 直接判误检，压到阈值以下
        if not corner_hit(x, y, frame.shape[1], frame.shape[0]):
            score *= 0.35
        elif not self._verify(frame, x, y, self.base_w, self.base_h):
            score *= 0.5   # 位置对但结构不符（下方没有「抖音号」白字行）
        self.scores.append(score)
        return x, y, score, s


def mask_box_from_hit(x, y, W=10 ** 9, H=10 ** 9):
    """由文字行命中点推出水印整块 bbox（基于基准尺度）。"""
    dx0, dy0, dx1, dy1 = MASK_EXPAND
    return (max(0, x + dx0), max(0, y + dy0),
            min(W, x + 700 - 448 + dx1), min(H, y + 1220 - 1182 + dy1))


def refine_box(frame, hit, pad=8, max_gap=32):
    """从文字行锚点向上下左右扫描白色水印信号，自动求出水印块真实边界。

    不同版本抖音的水印排版不同（logo 行距文字行 77px 或 120px），
    固定外扩量会漏遮，这里让边界沿着信号自己长出来。
    """
    H, W = frame.shape[:2]
    hx, hy = hit
    rx0 = max(0, hx - 30)
    rx1 = min(W, hx + 300)
    ry0 = max(0, hy - 150)
    ry1 = min(H, hy + 95)
    if rx1 - rx0 < 40 or ry1 - ry0 < 40:
        return None
    roi = frame[ry0:ry1, rx0:rx1]
    Wd = roi.min(axis=2)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    top = cv2.morphologyEx(Wd, cv2.MORPH_TOPHAT, k)
    sig = ((top > 26) & (Wd > 155)).astype(np.uint8)

    row_sig = sig.sum(axis=1) > max(4, int(sig.shape[1] * 0.015))
    col_sig = sig.sum(axis=0) > max(4, int(sig.shape[0] * 0.015))

    def span(flags, center):
        n = len(flags)
        c = int(min(max(center, 0), n - 1))
        # 锚点附近若没信号，先就近找个有信号的位置
        if not flags[c]:
            near = np.where(flags)[0]
            if len(near) == 0:
                return None
            c = int(near[np.argmin(np.abs(near - c))])
        lo = c
        gap = 0
        while lo > 0:
            if flags[lo - 1]:
                gap = 0
            else:
                gap += 1
                if gap > max_gap:
                    break
            lo -= 1
        hi = c
        gap = 0
        while hi < n - 1:
            if flags[hi + 1]:
                gap = 0
            else:
                gap += 1
                if gap > max_gap:
                    break
            hi += 1
        return lo, hi

    rs = span(row_sig, hy - ry0)
    cs = span(col_sig, hx - rx0)
    if rs is None or cs is None:
        return None

    d = mask_box_from_hit(hx, hy)
    y0 = ry0 + rs[0] - pad
    y1 = ry0 + rs[1] + pad
    x0 = rx0 + cs[0] - pad
    x1 = rx0 + cs[1] + pad

    # 限幅：允许在默认框基础上外扩，但不许跑飞
    y0 = min(max(y0, d[1] - 80), hy)
    y1 = max(min(y1, d[3] + 80), hy + 40)
    x0 = min(max(x0, d[0] - 50), hx)
    x1 = max(min(x1, d[2] + 80), hx + 120)

    if (x1 - x0) < 100 or (y1 - y0) < 50:
        return None
    return (max(0, x0), max(0, y0), min(W, x1), min(H, y1))


AT_TEMPLATE = BASE / "models" / "wm_template_at.png"


class AtNameDetector:
    """检测 "@昵称" 那种单独一行的半透明水印（没有 logo 和抖音号）。

    这种水印字号会随版本变化，所以做宽范围多尺度匹配；
    只在四个角带里搜，避免画面中部的内容（尤其硬字幕）误命中。
    """

    SCALES = (0.85, 0.95, 1.05, 1.15, 1.25, 1.35, 1.45, 1.55, 1.65, 1.75)

    def __init__(self, path=AT_TEMPLATE, thresh=0.62):
        img = cv2.imread(str(path))
        if img is None:
            raise FileNotFoundError(f"@昵称模板不存在: {path}")
        tpl = img.min(axis=2).astype(np.float32)
        self.tpls = [(s, cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA))
                     for s in self.SCALES]
        self.thresh = thresh
        self.base_w, self.base_h = tpl.shape[1], tpl.shape[0]

    @staticmethod
    def _bands(H, W):
        return [
            (0, 0, int(W * 0.60), int(H * 0.30)),                    # 左上
            (int(W * 0.40), 0, W, int(H * 0.30)),                    # 右上
            (0, int(H * 0.58), int(W * 0.60), H),                    # 左下
            (int(W * 0.40), int(H * 0.58), W, H),                    # 右下
        ]

    def detect(self, frame):
        """返回 (score, x, y, w, h)；x,y 为该尺度下命中框左上角。"""
        H, W = frame.shape[:2]
        Wd = frame.min(axis=2).astype(np.float32)
        best = (-1.0, 0, 0, 0, 0)
        for bx0, by0, bx1, by1 in self._bands(H, W):
            roi = Wd[by0:by1, bx0:bx1]
            if roi.size == 0:
                continue
            for s, t in self.tpls:
                th, tw = t.shape
                if th >= roi.shape[0] or tw >= roi.shape[1]:
                    continue
                res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
                _, mx, _, loc = cv2.minMaxLoc(res)
                if mx > best[0]:
                    best = (mx, bx0 + loc[0], by0 + loc[1], tw, th)
        return best


AT_SYMBOL = BASE / "models" / "wm_at_symbol.png"


class AtSymbolDetector:
    """检测 "@账号名" 形态的水印：只匹配 "@" 符号本身（跨账号通用），
    命中后再验证其右侧确有半透明白字，防止画面里零星的 @ 造成误检。"""

    SCALES = (0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.35, 1.50, 1.65)

    def __init__(self, path=AT_SYMBOL, thresh=0.72):
        img = cv2.imread(str(path))
        if img is None:
            raise FileNotFoundError(f"@ 模板不存在: {path}")
        tpl = img.min(axis=2).astype(np.float32)
        self.tpls = [(s, cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA))
                     for s in self.SCALES]
        self.thresh = thresh
        self.base_w, self.base_h = tpl.shape[1], tpl.shape[0]

    def detect(self, frame):
        """返回 (score, x, y, w, h)；未命中时 x=y=0。"""
        Wd = frame.min(axis=2).astype(np.float32)
        H, W = frame.shape[:2]
        best = (-1.0, 0, 0, 0, 0)
        for s, t in self.tpls:
            th, tw = t.shape
            if th >= H or tw >= W:
                continue
            res = cv2.matchTemplate(Wd, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx > best[0]:
                best = (mx, loc[0], loc[1], tw, th)
        score, x, y, w, h = best
        if score < self.thresh:
            return (score, 0, 0, 0, 0)
        # 右侧必须跟着一串白字（账号名），否则当误检丢掉
        rx0, rx1 = min(x + w + 3, W - 1), min(x + w + 200, W)
        ry0, ry1 = max(0, y - 6), min(H, y + h + 6)
        if rx1 - rx0 < 30:
            return (score, 0, 0, 0, 0)
        roi = frame[ry0:ry1, rx0:rx1]
        Wr = roi.min(axis=2)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        top = cv2.morphologyEx(Wr, cv2.MORPH_TOPHAT, k)
        ratio = float(((top > 12) & (Wr > 140)).mean())
        if ratio < 0.03:
            return (score * 0.5, 0, 0, 0, 0)
        return (score, x, y, w, h)


# ---------------------------------------------------------------- 修复后端
class LamaOnnx:
    def __init__(self, provider="CPU"):
        import onnxruntime as ort

        providers = (["DmlExecutionProvider", "CPUExecutionProvider"]
                     if provider.upper() == "DML" else ["CPUExecutionProvider"])
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(str(MODEL_ONNX), sess_options=so, providers=providers)
        self.name = f"LaMa-ONNX({self.sess.get_providers()[0]})"

    def __call__(self, crop, mcrop):
        img_in = crop[:, :, ::-1].astype(np.float32) / 255.0
        img_in = np.transpose(img_in, (2, 0, 1))[None]
        mask_in = (mcrop > 127).astype(np.float32)[None, None]
        out = self.sess.run(None, {"image": img_in, "mask": mask_in})[0]
        res = np.transpose(out[0], (1, 2, 0))[:, :, ::-1]
        if res.max() <= 1.5:
            res *= 255.0
        return np.clip(res, 0, 255).astype(np.uint8)


class LamaTorch:
    """直接加载 big-lama.pt（TorchScript），用 CUDA/MPS/CPU 推理。"""

    def __init__(self, device="cuda"):
        import torch

        self.torch = torch
        if device == "cuda" and torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")
        self.model = torch.jit.load(str(MODEL_PT), map_location=self.device).eval()
        try:
            self.model = self.model.to(self.device)
        except Exception:
            pass
        gpu = torch.cuda.get_device_name(0) if self.device.type == "cuda" else self.device.type
        self.name = f"LaMa-Torch({gpu})"

    def __call__(self, crop, mcrop):
        torch = self.torch
        rgb = crop[:, :, ::-1].astype(np.float32) / 255.0
        img = torch.from_numpy(np.ascontiguousarray(np.transpose(rgb, (2, 0, 1))))[None]
        m = torch.from_numpy(np.ascontiguousarray((mcrop > 127).astype(np.float32)))[None, None]
        img = img.to(self.device)
        m = m.to(self.device)
        with torch.inference_mode():
            out = self.model(img, m)
        res = (out["inpainted"] if isinstance(out, dict) else out)[0]
        res = res.detach().float().cpu().numpy()
        res = np.transpose(res, (1, 2, 0))[:, :, ::-1]
        if res.max() <= 1.5:
            res *= 255.0
        return np.clip(res, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- 修复工具
def _window(box, shape, size=WIN):
    H, W = shape[:2]
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    wx = min(max(cx - size // 2, 0), max(W - size, 0))
    wy = min(max(cy - size // 2, 0), max(H - size, 0))
    return wx, wy, min(wx + size, W), min(wy + size, H)


def repair(frame, mask, box, backend, feather=7):
    H, W = frame.shape[:2]
    wx0, wy0, wx1, wy1 = _window(box, frame.shape)
    crop = frame[wy0:wy1, wx0:wx1]
    mcrop = mask[wy0:wy1, wx0:wx1]

    ch, cw = crop.shape[:2]
    ph, pw = WIN - ch, WIN - cw
    if ph or pw:
        crop = cv2.copyMakeBorder(crop, 0, max(ph, 0), 0, max(pw, 0), cv2.BORDER_REFLECT)
        mcrop = cv2.copyMakeBorder(mcrop, 0, max(ph, 0), 0, max(pw, 0), cv2.BORDER_CONSTANT, value=0)

    res = backend(crop, mcrop)[:ch, :cw]

    alpha = cv2.GaussianBlur((mcrop[:ch, :cw] > 127).astype(np.float32), (feather * 2 + 1,) * 2, 0)
    alpha = alpha[:, :, None]
    base = frame[wy0:wy1, wx0:wx1].astype(np.float32)
    out = frame.copy()
    out[wy0:wy1, wx0:wx1] = (res.astype(np.float32) * alpha + base * (1 - alpha)).astype(np.uint8)
    return out


def _median1d(a, k):
    from numpy.lib.stride_tricks import sliding_window_view
    pad = k // 2
    ap = np.pad(a, pad, mode="edge")
    return np.median(sliding_window_view(ap, k), axis=1)


def smooth_positions(hits, scores, win=15, thresh=0.40):
    """对检测结果做时间中值平滑，抑制单帧误检导致的 mask 跳变。"""
    xs = np.array([h[0] for h in hits], dtype=np.float32)
    ys = np.array([h[1] for h in hits], dtype=np.float32)
    valid = np.array([s >= thresh for s in scores])
    if win > 1 and len(xs) > 2:
        k = min(win if win % 2 else win + 1, len(xs) if len(xs) % 2 else len(xs) - 1)
        k = max(k, 1)
        if k > 1:
            xs = _median1d(xs, k)
            ys = _median1d(ys, k)
    return xs.astype(int), ys.astype(int), valid


def parse_extra_masks(specs, W, H, fps):
    """解析 "x0,y0,x1,y1[,起始秒][,结束秒]" 形式的补遮区。"""
    out = []
    for s in specs or []:
        parts = [p.strip() for p in s.replace("，", ",").split(",") if p.strip()]
        if len(parts) < 4:
            print(f"  [警告] 补遮区格式不对，已忽略: {s}")
            continue
        try:
            x0, y0, x1, y1 = (int(float(p)) for p in parts[:4])
        except ValueError:
            print(f"  [警告] 补遮区坐标不是数字，已忽略: {s}")
            continue
        f0 = int(float(parts[4]) * fps) if len(parts) > 4 and parts[4] else 0
        f1 = int(float(parts[5]) * fps) if len(parts) > 5 and parts[5] else 10 ** 9
        out.append((max(0, x0), max(0, y0), min(W, x1), min(H, y1), f0, f1))
    return out


# ---------------------------------------------------------------- 主处理
def process_video(src: Path, outdir: Path, backend, limit=0, trim_tail=0.0,
                  mask_scale=1.0, quiet=False, detect_at=True, extra_masks=None,
                  template=None, expand=None, detect_interval=15, replace=False,
                  use_refine=True, out_suffix=DEFAULT_SUFFIX):
    global MASK_EXPAND
    if expand is not None:
        MASK_EXPAND = expand
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        print(f"[跳过] 打不开 {src}")
        return None
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    n = min(n_total - int(fps * trim_tail), limit) if limit else n_total - int(fps * trim_tail)
    n = max(n, 1)

    print(f"\n=== {src.name}  {W}x{H} @{fps:.2f}fps  共 {n_total} 帧，处理 {n} 帧 ===")
    det = WatermarkDetector(template or TEMPLATE)
    print(f"  模板 {os.path.basename(str(template or TEMPLATE))}  "
          f"{det.base_w}x{det.base_h}  检测间隔 {detect_interval} 帧")

    # 第一遍：按 detect_interval 采样检测（水印位置在 1 秒内稳定），再回填到每帧
    t0 = time.time()
    hits, scores = [], []
    at_hits, at_scores = [], []
    at_sym_hits, at_sym_scores = [], []
    try:
        at_det = AtNameDetector() if detect_at else None
    except FileNotFoundError as e:
        print(f"  [警告] {e}，跳过 @昵称 水印检测")
        at_det = None

    step = max(1, detect_interval)
    idxs = list(range(0, n, step))
    if idxs and idxs[-1] != n - 1:
        idxs.append(n - 1)
    sampled = {}
    try:
        at_sym_det = AtSymbolDetector()
    except FileNotFoundError as e:
        print(f"  [警告] {e}，跳过 @账号名 检测")
        at_sym_det = None
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            continue
        x, y, sc, s = det.detect(fr)
        a = (0, 0, 0, 0, 0)
        if at_det is not None:
            asc, ax, ay, aw, ah = at_det.detect(fr)
            a = (asc, ax, ay, aw, ah)
        b = (0, 0, 0, 0, 0)
        if at_sym_det is not None:
            b = at_sym_det.detect(fr)
        sampled[i] = (x, y, sc) + a + b
        if not quiet and len(sampled) % 20 == 0:
            print(f"  采样检测 {len(sampled)}/{len(idxs)}  score={sc:.2f} pos=({x},{y}) "
                  f"@{b[0]:.2f}", end="\r")
    cap.release()

    if not sampled:
        print("  [失败] 一帧都没检测到")
        return None
    keys = np.array(sorted(sampled), dtype=np.int64)
    pos = np.searchsorted(keys, np.arange(n))
    pos = np.clip(pos, 0, len(keys) - 1)
    # 就近取采样点（不插值：水印位置是阶跃变化，插值会得到不存在的中间位置）
    for i in range(n):
        k = keys[pos[i]]
        v = sampled[k]
        hits.append((v[0], v[1]))
        scores.append(v[2])
        at_scores.append(v[3])
        at_hits.append((v[4], v[5], v[6], v[7]))
        at_sym_scores.append(v[8])
        at_sym_hits.append((v[9], v[10], v[11], v[12]))
    n = len(hits)
    if at_det is None:
        at_scores, at_hits = [0.0] * n, [(0, 0, 0, 0)] * n
    if at_sym_det is None:
        at_sym_scores, at_sym_hits = [0.0] * n, [(0, 0, 0, 0)] * n
    det_cost = time.time() - t0
    xs, ys, valid = smooth_positions(hits, scores, thresh=det.thresh)
    print(f"\n  检测耗时 {det_cost:.1f}s，有效水印帧 {int(valid.sum())}/{n}"
          f"，位置集合 {sorted(set(map(tuple, np.unique(np.c_[xs, ys], axis=0))))[:6]}")

    # 片尾抖音 UI 页会让模板命中到画面中央（头像/搜索框），这里按"是否贴角"过滤并截断尾巴
    from collections import Counter

    def _corner_ok(x, y, W, H):
        near_t = y < H * 0.30
        near_b = y > H * 0.62
        near_l = x < W * 0.28
        near_r = x > W * 0.50
        return (near_t or near_b) and (near_l or near_r)

    keys = [(int(xs[i]) // 12, int(ys[i]) // 12) for i in range(n)]
    corner = np.array([_corner_ok(xs[i], ys[i], W, H) for i in range(n)])
    dropped_corner = int((valid & ~corner).sum())
    valid = valid & corner
    if dropped_corner:
        print(f"  过滤掉 {dropped_corner} 帧非贴角命中（画面中部 = 片尾 UI 页）")

    # ★ 先判识别率，再谈截尾。否则全部未命中时下面的截尾会把整条片子退到 0 帧，
    #   输出一个空壳文件（--replace 模式下还会毁掉原片）。
    n_valid = int(valid.sum())
    if n_valid < max(8, int(n * 0.15)):
        print(f"  [跳过] 有效水印帧仅 {n_valid}/{n}（<15%），模板未匹配，保留原片不动")
        return None

    cnt = Counter(keys[i] for i in range(n) if valid[i])
    main = set()
    if cnt:
        th = max(4, int(n * 0.05))
        main = {k for k, c in cnt.items() if c >= th}
        cut = n
        for i in range(n - 1, -1, -1):
            if valid[i] and keys[i] in main:
                break
            cut = i
        # 截尾保护：最多截掉末尾 25%，避免误判把正片当片尾删掉
        if cut < n and (n - cut) <= n * 0.25:
            print(f"  截掉最后 {n - cut} 帧（{(n-cut)/fps:.1f}s 片尾）")
            n = cut
        elif cut < n:
            print(f"  [警告] 疑似片尾 {n - cut} 帧超过全片 25%，判定为识别异常，不截尾")
        valid = np.array([valid[i] and keys[i] in main for i in range(len(valid))][:n])
        print(f"  过滤后有效帧 {int(valid.sum())}/{n}，主位置 {sorted(main)}")

    # 兜底：截尾后仍需有足够多的有效帧，且不能为 0
    if n < 2 or int(valid.sum()) < max(8, int(n * 0.15)):
        print(f"  [跳过] 截尾后有效帧 {int(valid.sum())}/{n} 不足，保留原片不动")
        return None

    # 第二遍：修复（直接通过管道喂给 ffmpeg，一次编码无损输出）
    #
    # 先写 `.part.mp4`，等时长校验通过后再改名成最终文件。
    # 原因：ffmpeg 只在正常结束时才写 moov 索引（`+faststart` 还要回填文件头）。
    # 进程被 Ctrl+C / 超时 / 关窗口杀掉时，留下的是几十 MB 没有 moov 的裸数据——
    # Windows 里不显示缩略图、双击放不了，还会被当成品混在目录里。
    # 中间态用 .part 后缀，一眼能认出来，下次启动也会自动清掉。
    final = outdir / f"{src.stem}{out_suffix}.mp4"
    tmp_out = outdir / f"{src.stem}{out_suffix}.part.mp4"
    if tmp_out.exists():
        tmp_out.unlink()
    has_audio = _has_audio(src)
    cmd = [str(FFMPEG), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-"]
    if has_audio:
        cmd += ["-i", str(src), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"]
    else:
        cmd += ["-map", "0:v:0"]
    cmd += ["-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(tmp_out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    cap = cv2.VideoCapture(str(src))
    t0 = time.time()
    box_cache = {}
    # 主位置的遮罩框。抖音水印在一条片子里位置固定，但模板匹配会因背景明暗在
    # 部分帧失效（实测同一视频只有 28% 帧能命中）。只看命中帧去修，剩下的帧水印
    # 会原样留着，播放时一眼就能看到。所以未命中的帧也按主位置补遮。
    # 每个主位置记录"出现时段 + 遮罩框"。只在该时段补遮，不要全片一刀切：
    # 多场景拼接时，A 场景左上角是水印，B 场景同一位置可能是正常文字（如批准文号），
    # 全片补遮会把 B 场景的字也糊掉。
    main_meta = []
    for k in sorted(main):
        fs = [i for i in range(n) if valid[i] and keys[i] == k]
        if not fs:
            continue
        box = mask_box_from_hit(int(k[0]) * 12, int(k[1]) * 12, W, H)
        if box[3] >= H - 8:
            # 水印纵向位置在不同分段会浮动（实测 y 从 1000 到 1200 都有），
            # 贴底时统一从 H-280 起，覆盖位置更高的那些场景。
            new_y0 = min(box[1], H - 280)
            print(f"  贴底遮罩 {box} → 整行 (0,{new_y0},{W},{H})，底部说明小字一并移除")
            box = (0, new_y0, W, H)
        # 出现得多的位置按全片处理：检测本身不稳（这条片子 28% 命中），
        # 出现范围会被截断，严格按时段反而漏掉后面的场景。
        # 只在局部零星出现的位置才限制时段，避免误伤其他场景的正常内容。
        ratio = len(fs) / max(n, 1)
        if ratio >= 0.15:
            f0, f1 = 0, n - 1
            note = f"全片（出现率 {ratio*100:.0f}%）"
        else:
            pad = int(n * 0.2)
            f0, f1 = max(0, min(fs) - pad), min(n - 1, max(fs) + pad)
            note = f"局部 {f0}~{f1}（出现率 {ratio*100:.0f}%，外扩 20%）"
        main_meta.append((f0, f1, box))
        print(f"  位置 {k} → {note}，遮罩 {box}")
    at_pad = 12
    n_at_fixed = 0
    n_at_sym = 0
    n_extra = 0
    n_fallback = 0
    extra_list = parse_extra_masks(extra_masks, W, H, fps)
    if extra_list:
        print(f"  补遮区 {len(extra_list)} 个: "
              + ", ".join(f"{e[:4]}@{e[4]/fps:.1f}-{e[5]/fps:.1f}s" for e in extra_list))
    pipe_dead = False
    for i in range(n):
        ok, fr = cap.read()
        if not ok:
            break
        # 按"该位置此帧是否处于出现时段"决定补遮：命中帧用自己的框，
        # 未命中帧在该位置的时段内也补遮（检测不稳时保证不漏）。
        boxes = [b for (f0, f1, b) in main_meta if f0 <= i <= f1]
        if valid[i]:
            key = (int(xs[i]) // 12, int(ys[i]) // 12)
            if key in main:
                n_fallback += 1          # 与主位置重合，已由 main_meta 覆盖
            else:
                # 该帧还有一个主位置之外的水印（多段拼接时常见），额外补遮
                if key not in box_cache:
                    rb = refine_box(fr, (int(xs[i]), int(ys[i]))) if use_refine else None
                    box_cache[key] = rb if rb else mask_box_from_hit(xs[i], ys[i], W, H)
                    print(f"\n  mask[{key}] -> {box_cache[key]}"
                          f"{' (自动精修)' if rb else ' (默认框)'}")
                bx0, by0, bx1, by1 = box_cache[key]
                if mask_scale != 1.0:
                    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
                    half = ((bx1 - bx0) * mask_scale / 2, (by1 - by0) * mask_scale / 2)
                    bx0, bx1 = int(cx - half[0]), int(cx + half[0])
                    by0, by1 = int(cy - half[1]), int(cy + half[1])
                boxes.append((max(bx0, 0), max(by0, 0), min(bx1, W), min(by1, H)))
        elif boxes:
            n_fallback += 1

        # @昵称 那种单独一行的半透明水印，位置通常在另一个角，单独出框
        if at_det is not None and at_scores[i] >= at_det.thresh:
            ax, ay, aw, ah = at_hits[i]
            boxes.append((max(ax - at_pad, 0), max(ay - at_pad, 0),
                          min(ax + aw + at_pad, W), min(ay + ah + at_pad, H)))
            n_at_fixed += 1

        # "@账号名" 形态：@ 符号向右扩展覆盖整个昵称
        if at_sym_det is not None and at_sym_scores[i] >= at_sym_det.thresh:
            sx, sy, sw, sh = at_sym_hits[i]
            if sw > 0:
                boxes.append((max(sx - 12, 0), max(sy - 12, 0),
                              min(sx + 270, W), min(sy + sh + 16, H)))
                n_at_sym += 1

        # 手动补遮区（针对低对比水印/平台特殊排版）
        for (ex0, ey0, ex1, ey1, ef0, ef1) in extra_list:
            if ef0 <= i < ef1:
                boxes.append((ex0, ey0, ex1, ey1))
                n_extra += 1

        for b in boxes:
            if b[2] - b[0] < 8 or b[3] - b[1] < 8:
                continue
            mask = np.zeros((H, W), np.uint8)
            cv2.rectangle(mask, (b[0], b[1]), (b[2], b[3]), 255, -1)
            fr = repair(fr, mask, b, backend)
        try:
            proc.stdin.write(fr.tobytes())
        except (BrokenPipeError, OSError) as e:
            print(f"\n  [失败] 写入 ffmpeg 管道中断：{e}")
            pipe_dead = True
            break
        if not quiet and i % 10 == 0:
            el = time.time() - t0
            eta = el / (i + 1) * (n - i - 1)
            print(f"  修复 {i:4d}/{n}  {el:.0f}s  剩余 {eta:.0f}s", end="\r")
    cap.release()
    if pipe_dead:
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        # 管道断了 ffmpeg 可能还在等输入，直接杀掉，避免读 stderr 时卡死
        try:
            proc.kill()
        except OSError:
            pass
        err2 = proc.stderr.read().decode("utf-8", "ignore")
        proc.wait()
        print("  [ffmpeg 失败]", err2[-500:])
        _discard(tmp_out)
        return None
    try:
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    err = proc.stderr.read().decode("utf-8", "ignore")
    proc.wait()
    print(f"\n  修复耗时 {time.time()-t0:.1f}s，其中 {n_at_fixed} 帧补修了 @昵称 水印"
          f"，{n_at_sym} 帧补修了 @账号名 水印，{n_extra} 帧应用了补遮区")
    if proc.returncode != 0:
        print("  [ffmpeg 失败]", err[-500:])
        _discard(tmp_out)
        return None

    # 成品校验：必须能被解析出时长（moov 缺失 / 空壳 / 时长偏离都算无效），
    # 通过后才改名成最终文件，避免把半成品留在目录里。
    expect = n / fps if fps else 0
    got = _probe_duration(tmp_out)
    if not got:
        print("  [失败] 输出无法解析（缺 moov 索引，通常是编码中断），已丢弃")
        _discard(tmp_out)
        return None
    if expect and (got < expect * 0.5 or got > expect * 1.5):
        print(f"  [失败] 输出时长 {got:.1f}s 与预期 {expect:.1f}s 偏差过大，判定无效")
        _discard(tmp_out)
        return None
    os.replace(tmp_out, final)
    print(f"  ✔ 输出 {final.name}  ({final.stat().st_size/1e6:.1f} MB，{got:.1f}s)")

    if replace:
        try:
            if final.stat().st_size < 10240:
                print("  [跳过替换] 输出文件异常小，保留原片")
            else:
                same = final.resolve() == src.resolve()
                src.unlink()
                if not same:
                    final.replace(src)
                print(f"  已用无水印版替换原片 {src.name}")
        except Exception as e:
            print(f"  [警告] 替换原片失败：{e}")
    return final


def _discard(p: Path):
    """删掉写了一半的中间产物（失败/中断时用，不要留成假成品）。"""
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


def _has_audio(p: Path):
    try:
        r = subprocess.run([str(FFMPEG), "-i", str(p)], capture_output=True, text=True, errors="ignore")
        return "Audio:" in r.stderr
    except Exception:
        return False


def _probe_duration(p: Path) -> float:
    """取**视频流**时长（秒），失败退回容器时长，再失败返回 0。

    为什么不能直接读容器时长：音轨是 `-c:a copy` 原样搬过来的，音频比视频长时
    （VFR 片子、或 --limit 只处理片段）容器时长会被音轨撑大，
    于是"输出 44s vs 预期 5s"这种假失败就出来了。
    """
    probe = FFMPEG.with_name("ffprobe.exe")
    for args in (
        ["-select_streams", "v:0", "-show_entries", "stream=duration"],
        ["-show_entries", "format=duration"],
    ):
        try:
            r = subprocess.run([str(probe), "-v", "error", *args,
                                "-of", "default=nw=1:nk=1", str(p)],
                               capture_output=True, text=True, errors="ignore", timeout=30)
            val = (r.stdout or "").strip().splitlines()
            v = float(val[0]) if val and val[0] not in ("N/A", "") else 0.0
            if v > 0:
                return v
        except Exception:
            continue
    return 0.0


def main():
    ap = argparse.ArgumentParser(description="抖音短视频水印清除（LaMa 修复）")
    ap.add_argument("-i", "--input", required=True, help="视频文件或目录")
    ap.add_argument("-o", "--output", default=str(BASE / "output"), help="输出目录")
    ap.add_argument("--backend", default="auto", choices=["auto", "torch", "onnx", "cpu", "dml"])
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 帧（调试用）")
    ap.add_argument("--trim-tail", type=float, default=0.0, help="裁掉片尾 N 秒（抖音推荐页 UI）")
    ap.add_argument("--mask-scale", type=float, default=1.0, help="mask 缩放，>1 遮得更大")
    ap.add_argument("--no-at", action="store_true", help="关闭 @昵称 水印的额外检测")
    ap.add_argument("--extra-mask", action="append", default=[], metavar="X0,Y0,X1,Y1[,起,止]",
                    help='额外强制遮挡区（秒），可重复。例：--extra-mask "20,820,215,860,23,29.5"')
    ap.add_argument("--template", default="default", choices=["default", "generic"],
                    help="default=固定账号文字行模板；generic=跨账号通用的「抖音」二字模板")
    ap.add_argument("--detect-interval", type=int, default=15,
                    help="每隔多少帧采样检测一次水印位置（默认 15，越大越快但位置切换会滞后）")
    ap.add_argument("--replace", action="store_true",
                    help="处理成功后删除原始带水印视频")
    ap.add_argument("--out-suffix", default=DEFAULT_SUFFIX,
                    help=f"输出文件名后缀（默认 {DEFAULT_SUFFIX}）")
    args = ap.parse_args()

    backend = None
    order = {"auto": ["torch", "onnx"], "torch": ["torch"], "onnx": ["onnx"],
             "cpu": ["onnx"], "dml": ["onnx"]}.get(args.backend, ["onnx"])
    for name in order:
        try:
            backend = LamaTorch("cuda") if name == "torch" else LamaOnnx(
                "DML" if args.backend == "dml" else "CPU")
            print(f"后端: {backend.name}")
            break
        except Exception as e:
            print(f"[{name}] 不可用: {type(e).__name__}: {e}")
    if backend is None:
        sys.exit("没有可用的修复后端")

    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)

    src = Path(args.input)
    if src.is_dir():
        files = sorted(src.rglob("*.mp4"))
    else:
        files = [src]
    files = [f for f in files
             if DEFAULT_SUFFIX not in f.stem and LEGACY_SUFFIX not in f.stem
             and not f.name.startswith(".")]
    print(f"待处理 {len(files)} 个视频")

    tpl = TPL_GENERIC if args.template == "generic" else TEMPLATE
    exp = EXPAND_GENERIC if args.template == "generic" else None

    t0 = time.time()
    done, failed = [], []
    for k, f in enumerate(files, 1):
        od = f.parent if args.replace else outdir
        print(f"\n[{k}/{len(files)}]")
        try:
            r = process_video(f, od, backend, limit=args.limit,
                              trim_tail=args.trim_tail, mask_scale=args.mask_scale,
                              detect_at=not args.no_at, extra_masks=args.extra_mask,
                              template=tpl, expand=exp,
                              detect_interval=args.detect_interval, replace=args.replace,
                              use_refine=(args.template != "generic"),
                              out_suffix=args.out_suffix)
        except Exception as e:
            print(f"  [异常] {type(e).__name__}: {e}")
            r = None
        (done if r else failed).append(f)

    el = time.time() - t0
    print(f"\n全部完成：成功 {len(done)}，失败 {len(failed)}，用时 {el/60:.1f} 分钟")
    for f in failed:
        print("  [失败]", f)


if __name__ == "__main__":
    main()
