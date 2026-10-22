"""LaMa ONNX 单帧推理测试：512x512 局部窗口裁切修复。"""
import cv2
import numpy as np
import onnxruntime as ort
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
MODEL = BASE / "models" / "lama_fp32.onnx"
FRAMES = BASE / "frames"
WIN = 512

_session = None


def get_session():
    global _session
    if _session is None:
        import os
        prov = os.environ.get("LAMA_PROVIDER", "CPU")
        providers = (["DmlExecutionProvider", "CPUExecutionProvider"] if prov == "DML"
                     else ["CPUExecutionProvider"])
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.intra_op_num_threads = 0
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        t0 = time.time()
        _session = ort.InferenceSession(str(MODEL), sess_options=so, providers=providers)
        print(f"模型加载 {time.time()-t0:.1f}s  使用 {_session.get_providers()[0]}")
    return _session


def _window(box, shape, size=WIN):
    """以 box 为中心取 size x size 窗口，并保证在画面内。"""
    H, W = shape[:2]
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    wx = min(max(cx - size // 2, 0), max(W - size, 0))
    wy = min(max(cy - size // 2, 0), max(H - size, 0))
    return wx, wy, min(wx + size, W), min(wy + size, H)


def inpaint_region(bgr, mask, box, feather=9):
    """只对 box 附近做 LaMa 修复，结果混合回原图。"""
    sess = get_session()
    H, W = bgr.shape[:2]
    wx0, wy0, wx1, wy1 = _window(box, bgr.shape)
    crop = bgr[wy0:wy1, wx0:wx1]
    mcrop = mask[wy0:wy1, wx0:wx1]

    ch, cw = crop.shape[:2]
    # 补到 512（画面比窗口小时）
    pad_h, pad_w = WIN - ch, WIN - cw
    if pad_h or pad_w:
        crop = cv2.copyMakeBorder(crop, 0, pad_h, 0, pad_w, cv2.BORDER_REFLECT)
        mcrop = cv2.copyMakeBorder(mcrop, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=0)

    img_in = crop[:, :, ::-1].astype(np.float32) / 255.0
    img_in = np.transpose(img_in, (2, 0, 1))[None]
    mask_in = (mcrop > 127).astype(np.float32)[None, None]

    out = sess.run(None, {"image": img_in, "mask": mask_in})[0]
    res = np.transpose(out[0], (1, 2, 0))[:, :, ::-1]
    if res.max() <= 1.5:
        res = res * 255.0
    res = np.clip(res, 0, 255).astype(np.uint8)[:ch, :cw]

    # 羽化混合，避免接缝
    alpha = cv2.GaussianBlur((mcrop[:ch, :cw] > 127).astype(np.float32), (feather * 2 + 1,) * 2, 0)
    alpha = alpha[:, :, None]
    base = bgr[wy0:wy1, wx0:wx1].astype(np.float32)
    blended = res.astype(np.float32) * alpha + base * (1 - alpha)

    full = bgr.astype(np.float32).copy()
    full[wy0:wy1, wx0:wx1] = blended
    return np.clip(full, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    img = cv2.imread(str(FRAMES / "v1_f1_idx442.png"))
    mask = np.zeros(img.shape[:2], np.uint8)
    box = (444, 1098, 720, 1270)
    cv2.rectangle(mask, box[:2], box[2:], 255, -1)

    inpaint_region(img, mask, box)  # 预热
    t0 = time.time()
    out = inpaint_region(img, mask, box)
    print(f"首帧 {time.time()-t0:.2f}s")

    ts = []
    for _ in range(10):
        t = time.time()
        inpaint_region(img, mask, box)
        ts.append(time.time() - t)
    print(f"平均 {np.mean(ts)*1000:.0f} ms/帧")

    crop_o = img[1080:1280, 420:720]
    crop_r = out[1080:1280, 420:720]
    z = np.hstack([crop_o, np.full((200, 6, 3), 255, np.uint8), crop_r])
    z = cv2.resize(z, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(str(FRAMES / "lama_cmp_zoom.png"), z)
    print("saved lama_cmp_zoom.png")
