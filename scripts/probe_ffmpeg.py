#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动复现 ffmpeg 管道，把 stderr 完整打出来，定位 262 字节输出的原因。"""
import subprocess
import sys
from pathlib import Path

import cv2

FF = str(Path(r"D:\Data\DouDian\video-cleaner\tools\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"))
# 产物放 video-cleaner\output 下，不要放「带货短视频」——那里是流水线输入目录，
# 混进探测用的 mp4 会被当成待处理视频。
OUT_DIR = Path(r"D:\Data\DouDian\video-cleaner\output\_probe")
OUT = str(OUT_DIR / "probe_out.mp4")


def _pick_video():
    """取一个真实样本：优先命令行传参，否则用 带货短视频 里最新的一条。"""
    if len(sys.argv) > 1:
        return sys.argv[1]
    root = Path(r"D:\Data\DouDian\带货短视频")
    vids = [p for p in root.glob("*/*.mp4")
            if "_去水印版" not in p.stem and not p.name.endswith(".part.mp4")]
    if not vids:
        raise SystemExit("带货短视频 下还没有视频，先下载一批，或直接传路径：probe_ffmpeg.py <视频>")
    return str(max(vids, key=lambda p: p.stat().st_mtime))


SRC = _pick_video()
OUT_DIR.mkdir(parents=True, exist_ok=True)


def trial(extra_args, label):
    cap = cv2.VideoCapture(SRC)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cmd = [FF, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-",
           "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast"] + extra_args + [OUT]
    print(f"\n--- {label}: {W}x{H} @{fps} ---")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    written = 0
    for i in range(60):
        ok, fr = cap.read()
        if not ok:
            break
        try:
            p.stdin.write(fr.tobytes())
            written += 1
        except Exception as e:
            print(f"  写入第 {i} 帧失败: {type(e).__name__}: {e}")
            break
    cap.release()
    try:
        p.stdin.close()
    except Exception as e:
        print(f"  stdin close 失败: {e}")
    err = p.stderr.read().decode("utf-8", "ignore")
    p.wait()
    size = Path(OUT).stat().st_size if Path(OUT).exists() else 0
    print(f"  写入 {written} 帧, returncode={p.returncode}, 输出 {size} 字节")
    if err.strip():
        print("  stderr:", err.strip().replace("\n", "\n          ")[:600])
    else:
        print("  stderr: (空)")


def main():
    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    trial(["-pix_fmt", "yuv420p"], "当前逻辑（yuv420p + 原 fps）")
    trial(["-pix_fmt", "yuv422p"], "改 yuv422p")
    trial(["-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"], "强制偶数尺寸")
    trial(["-pix_fmt", "yuv420p", "-r", "30"], "降帧率到 30")
    return 0


if __name__ == "__main__":
    sys.exit(main())
