#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键重建 video-cleaner 的运行环境。

换电脑 / 重装后，克隆项目（不含 .venv、models/*.pt、tools/）执行本脚本，
即可把缺失的运行时依赖补齐：

    D:\\Install\\Python\\python.exe video-cleaner\\setup_env.py

做四件事：
  1. 建 .venv 并安装 Python 依赖（torch 走阿里镜像，其余走腾讯镜像）
  2. 下载 LaMa ONNX 模型（hf-mirror），用 SHA256 校验
  3. 下载便携版 ffmpeg 并解压到 tools/
  4. 检查 GPU 权重 big-lama.pt，缺失时给出获取方式

已存在的步骤会自动跳过，可重复执行。
"""
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE / ".venv"
PY = VENV / "Scripts" / "python.exe"
MODELS = HERE / "models"
TOOLS = HERE / "tools"

PIP_HOST = "https://mirrors.cloud.tencent.com/pypi/simple/"
PIP_HOST_ARGS = ["-i", PIP_HOST, "--trusted-host", "mirrors.cloud.tencent.com"]

# LaMa ONNX（CPU 后端保底）
ONNX_URLS = [
    "https://hf-mirror.com/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
    "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
]
ONNX_SIZE = 208044816
ONNX_SHA256 = "1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6"

FFMPEG_URLS = [
    "https://ghfast.top/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
    "/ffmpeg-master-latest-win64-gpl.zip",
    "https://gh-proxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
    "/ffmpeg-master-latest-win64-gpl.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
    "/ffmpeg-master-latest-win64-gpl.zip",
]

TORCH_WHEEL = ("torch==2.10.0+cu126",
               "https://mirrors.aliyun.com/pytorch-wheels/cu126/")


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f}{u}"
        n /= 1024


def step(msg):
    print(f"\n{'='*56}\n{msg}\n{'='*56}", flush=True)


def download(urls, dest: Path, expect_size=None, expect_sha=None, label=""):
    """依次尝试多个源下载，校验大小/哈希。"""
    if dest.exists():
        if expect_size and abs(dest.stat().st_size - expect_size) < 1024:
            print(f"  ✓ 已存在 {dest.name} ({human(dest.stat().st_size)})")
            return True
        print(f"  · 已存在但大小不符，重新下载 {dest.name}")
        dest.unlink()

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for i, url in enumerate(urls, 1):
        print(f"  源 {i}/{len(urls)}: {url[:70]}...")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = got * 100 // total
                        print(f"\r    {human(got)}/{human(total)} ({pct}%)", end="", flush=True)
                    else:
                        print(f"\r    {human(got)}", end="", flush=True)
            print()
            size = tmp.stat().st_size
            if expect_size and abs(size - expect_size) > 1024:
                raise ValueError(f"大小不符：{size} != {expect_size}")
            if expect_sha:
                h = hashlib.sha256(tmp.read_bytes()).hexdigest()
                if h != expect_sha:
                    raise ValueError(f"SHA256 不符：{h[:16]}...")
                print(f"    校验通过 {h[:16]}...")
            os.replace(tmp, dest)
            print(f"  ✓ {dest.name} ({human(size)})")
            return True
        except Exception as e:
            print(f"\n    失败：{type(e).__name__}: {str(e)[:120]}")
            if tmp.exists():
                tmp.unlink()
    print(f"  ✗ {label or dest.name} 全部源下载失败")
    return False


def run(cmd, desc, check=True):
    print(f"  $ {' '.join(str(c) for c in cmd)[:100]}")
    r = subprocess.run([str(c) for c in cmd])
    if check and r.returncode != 0:
        raise RuntimeError(f"{desc} 失败（returncode={r.returncode}）")
    return r.returncode == 0


def main():
    print("video-cleaner 环境重建")
    print(f"  目录: {HERE}")
    print(f"  Python: {sys.version.split()[0]} ({sys.executable})")

    # ---- 1. 虚拟环境 ----
    step("1/4  Python 虚拟环境")
    if PY.exists():
        print(f"  ✓ 已存在 {VENV}")
    else:
        print("  创建 venv ...")
        run([sys.executable, "-m", "venv", str(VENV)], "创建 venv")
        print(f"  ✓ 已创建 {VENV}")

    # ---- 2. Python 依赖 ----
    step("2/4  Python 依赖")
    def installed(pkg):
        r = subprocess.run([str(PY), "-c", f"import {pkg}"], capture_output=True)
        return r.returncode == 0

    if installed("cv2") and installed("numpy"):
        print("  ✓ opencv / numpy 已安装")
    else:
        print("  安装 requirements.txt ...")
        run([PY, "-m", "pip", "install", "-r", str(HERE / "requirements.txt")] + PIP_HOST_ARGS,
            "安装依赖")

    if installed("torch"):
        r = subprocess.run([str(PY), "-c", "import torch;print(torch.__version__, torch.cuda.is_available())"],
                           capture_output=True, text=True)
        print(f"  ✓ torch 已安装: {r.stdout.strip()}")
    else:
        print("  安装 torch（CUDA 12.6 版，约 2.6GB，需要几分钟）...")
        ver, index = TORCH_WHEEL
        run([PY, "-m", "pip", "install", ver, "-f", index], "安装 torch", check=False)
        if not installed("torch"):
            print("  ! torch 安装失败，将只能使用 ONNX(CPU) 后端")

    # ---- 3. 模型 ----
    step("3/4  LaMa 模型")
    onnx = MODELS / "lama_fp32.onnx"
    ok_onnx = download(ONNX_URLS, onnx, ONNX_SIZE, ONNX_SHA256, "LaMa ONNX")

    pt = MODELS / "big-lama.pt"
    if pt.exists():
        print(f"  ✓ GPU 权重已存在 big-lama.pt ({human(pt.stat().st_size)})")
    else:
        print("  ! 缺少 GPU 权重 big-lama.pt（205MB，TorchScript 格式）")
        print("    这是从 best.ckpt 转换来的，公开源只有 .ckpt 原始权重，无法直接下载。")
        print("    获取方式（任选其一）：")
        print("      a) 从旧机器/U 盘/网盘拷贝 models\\big-lama.pt 到本目录")
        print("      b) 下载 big-lama.zip 后自行 torch.jit 转换")
        print("      c) 不补也行，脚本会自动退回 ONNX(CPU) 后端，只是慢约 35 倍")

    # ---- 4. ffmpeg ----
    step("4/4  便携版 ffmpeg")
    ffdir = TOOLS / "ffmpeg-master-latest-win64-gpl"
    ffexe = ffdir / "bin" / "ffmpeg.exe"
    if ffexe.exists():
        print(f"  ✓ 已存在 {ffexe}")
    else:
        zpath = TOOLS / "ffmpeg.zip"
        if download(FFMPEG_URLS, zpath, None, None, "ffmpeg"):
            print("  解压 ...")
            TOOLS.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(TOOLS)
            zpath.unlink()
            # 有些包解压后的目录名不同，统一改名
            if not ffdir.exists():
                for d in TOOLS.iterdir():
                    if d.is_dir() and (d / "bin" / "ffmpeg.exe").exists():
                        d.rename(ffdir)
                        break
            print(f"  ✓ ffmpeg 就绪：{ffexe if ffexe.exists() else '未找到，请检查解压结果'}")

    # ---- 验证 ----
    step("环境自检")
    checks = [
        ("opencv", [PY, "-c", "import cv2;print(cv2.__version__)"]),
        ("numpy", [PY, "-c", "import numpy;print(numpy.__version__)"]),
        ("torch", [PY, "-c", "import torch;print(torch.__version__, 'cuda' if torch.cuda.is_available() else 'cpu')"]),
        ("ONNX 模型", [PY, "-c", f"import os;print(os.path.getsize(r'{onnx}'))"]),
        ("ffmpeg", [str(ffexe), "-version"]),
    ]
    all_ok = True
    for name, cmd in checks:
        try:
            r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                print(f"  ✓ {name}: {r.stdout.strip().splitlines()[0][:60]}")
            else:
                print(f"  ✗ {name}: 不可用")
                all_ok = False
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}")
            all_ok = False

    print("\n" + ("=" * 56))
    if all_ok:
        print("环境就绪。可以运行：run.bat  或  python scripts\\dewatermark.py -h")
    else:
        print("部分组件缺失，见上面 ✗ 项；ONNX 可用时仍能跑（CPU 模式）。")
    print("=" * 56)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
