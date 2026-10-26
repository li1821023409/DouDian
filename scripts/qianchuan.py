#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把下载的短视频转成巨量千川可用的素材规格。

巨量千川对上传素材的硬性要求：
    横版：宽高比 16:9，码率 ≥ 516kbps，≤ 1000M，1280x720 ≤ 分辨率 ≤ 2560x1440，4s ≤ 时长 ≤ 300s
    竖版：宽高比  9:16，码率 ≥ 516kbps，≤ 1000M， 720x1280 ≤ 分辨率 ≤ 1440x2560，4s ≤ 时长 ≤ 300s

2026-10-26 实测本项目下载的 72 条视频：
    宽高比全部为 9:16 ✓、时长 41~95s ✓、码率 1023~3092k ✓、体积 5.7~23.3M ✓，
    **唯一不合格的是分辨率**——
        576x1024  32 条   低于 720x1280 下限
        540x960    8 条   低于下限（差得更多）
        720x1270   4 条   高度差 10 像素
        720x1278   4 条   高度差 2 像素
        720x1280  24 条   完全合规，不动

处理方式（2026-10-26 调整）：
    · **原地替换**：文件名不变，转出一个合规版本后覆盖原视频。
      不产生 `_千川.mp4` 之类的新文件，目录里每条视频就只有一份
    · 已经合规的原样跳过，不重编码——重编码只损失画质，规格并不会更好
    · 分辨率不足的等比放大到 720x1280。插值不会让画面变清晰，但这是规格强制要求
    · 比例只差几个像素的（720x1270）补黑边到 720x1280，**不裁切内容**
    · 时长不在 4~300s 的无法通过转码修复，只报告，不动文件
    · 先写 `<名>.part.mp4`，校验尺寸/时长/码率全过才改名覆盖原片，
      中途中断不会毁掉原视频

用法：
    D:/Install/Python/python.exe scripts/qianchuan.py --dry-run         # 只体检，不改文件
    D:/Install/Python/python.exe scripts/qianchuan.py                   # 统一成合规格式（原地覆盖）
    D:/Install/Python/python.exe scripts/qianchuan.py --force           # 合规的也重编码

输出：原文件名不变；清单写到 `带货短视频/_千川清单.json`。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from video_rules import is_derived, is_partial  # noqa: E402

PROJ = Path(r"D:\Data\DouDian")
OUT_ROOT = PROJ / "带货短视频"
FFDIR = PROJ / "video-cleaner" / "tools" / "ffmpeg-master-latest-win64-gpl" / "bin"
FFMPEG = FFDIR / "ffmpeg.exe"
FFPROBE = FFDIR / "ffprobe.exe"

# ---- 千川规格常量 ----------------------------------------------------------
MIN_BITRATE = 516_000            # 码率下限 516kbps
MAX_BYTES = 1000 * 1024 * 1024   # 体积上限 1000M
MIN_DUR = 4.0
MAX_DUR = 300.0
RATIO_TOL = 0.01                 # 宽高比容差；720x1270 偏差 0.0044，仍在容差内

SPEC = {
    "portrait": dict(name="竖版", ratio=9 / 16, w=(720, 1440), h=(1280, 2560)),
    "landscape": dict(name="横版", ratio=16 / 9, w=(1280, 2560), h=(720, 1440)),
}


# ---- ffprobe 封装 ---------------------------------------------------------
def probe(path: Path) -> dict | None:
    r = subprocess.run(
        [str(FFPROBE), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return None
    try:
        d = json.loads(r.stdout)
    except Exception:
        return None

    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        return None
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)

    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    rot = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except Exception:
                pass
    tag = (v.get("tags") or {}).get("rotate")
    if tag:
        try:
            rot = int(float(tag))
        except Exception:
            pass
    # 手机视频常带旋转标记，实际显示尺寸要交换宽高
    dw, dh = (h, w) if abs(rot) % 180 == 90 else (w, h)

    fmt = d.get("format") or {}
    dur = float(v.get("duration") or fmt.get("duration") or 0)
    size = int(fmt.get("size") or (path.stat().st_size if path.exists() else 0))
    br = float(v.get("bit_rate") or 0)
    if not br and dur > 0:
        br = size * 8 / dur
    return dict(w=w, h=h, rot=rot, dw=dw, dh=dh, dur=dur, size=size, bitrate=br,
                codec=v.get("codec_name"), pix=v.get("pix_fmt"),
                fps=v.get("avg_frame_rate"), has_audio=a is not None)


def probe_duration(path: Path) -> float:
    """取视频流时长，失败退回容器时长（与 dewatermark.py 保持一致的取法）。"""
    for args in (["-select_streams", "v:0", "-show_entries", "stream=duration"],
                 ["-show_entries", "format=duration"]):
        r = subprocess.run([str(FFPROBE), "-v", "error", *args,
                            "-print_format", "json", str(path)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            continue
        try:
            d = json.loads(r.stdout)
        except Exception:
            continue
        if "streams" in d and d["streams"]:
            val = d["streams"][0].get("duration")
            if val and float(val) > 0:
                return float(val)
        val = (d.get("format") or {}).get("duration")
        if val and float(val) > 0:
            return float(val)
    return 0.0


# ---- 体检 -----------------------------------------------------------------
def classify(info: dict) -> tuple[str, list[str]]:
    """返回 (朝向, 不合格原因列表)。原因列表为空表示完全合规。"""
    dw, dh = info["dw"], info["dh"]
    if dh == 0:
        return "unknown", ["读不到分辨率"]
    ar = dw / dh
    kind = ("portrait" if abs(ar - 9 / 16) <= RATIO_TOL
            else "landscape" if abs(ar - 16 / 9) <= RATIO_TOL
            else "portrait" if dh > dw else "landscape")
    spec = SPEC[kind]
    bad = []

    if abs(ar - spec["ratio"]) > RATIO_TOL:
        bad.append(f"宽高比 {ar:.3f}，应为 {spec['ratio']:.3f}")
    if not (spec["w"][0] <= dw <= spec["w"][1] and spec["h"][0] <= dh <= spec["h"][1]):
        bad.append(f"分辨率 {dw}x{dh}（要求 {spec['w'][0]}x{spec['h'][0]}"
                   f"~{spec['w'][1]}x{spec['h'][1]}）")
    if info["bitrate"] < MIN_BITRATE:
        bad.append(f"码率 {info['bitrate']/1000:.0f}k < 516k")
    if info["size"] > MAX_BYTES:
        bad.append(f"体积 {info['size']/1048576:.0f}M > 1000M")
    if info["dur"] < MIN_DUR:
        bad.append(f"时长 {info['dur']:.1f}s < 4s（转码无法修复）")
    if info["dur"] > MAX_DUR:
        bad.append(f"时长 {info['dur']:.1f}s > 300s（转码无法修复）")
    return kind, bad


def unfixable(bad: list[str]) -> bool:
    return any(("无法修复" in b) for b in bad)


def pick_target(info: dict, kind: str) -> tuple[int, int]:
    """目标分辨率：保持源素材的量级，不低于规格下限、不超过上限。

    短边 ≥1080 的用 1080x1920（不降画质），否则用下限 720x1280。
    """
    spec = SPEC[kind]
    lo_w, hi_w = spec["w"]
    lo_h, hi_h = spec["h"]
    short = min(info["dw"], info["dh"])
    if kind == "portrait":
        w, h = (1080, 1920) if short >= 1080 else (lo_w, lo_h)
    else:
        w, h = (1920, 1080) if short >= 1080 else (lo_w, lo_h)
    # 夹到规格允许的区间内
    w = max(lo_w, min(w, hi_w))
    h = max(lo_h, min(h, hi_h))
    return w, h


# ---- 转码 -----------------------------------------------------------------
def build_vf(target: tuple[int, int]) -> str:
    """等比缩放后居中补黑边，保证不裁掉画面内容。"""
    w, h = target
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


def run_ffmpeg(src: Path, dst: Path, vf: str, info: dict,
               crf: int, force_bitrate: int | None) -> tuple[bool, str]:
    cmd = [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), "-map", "0:v:0"]
    if info.get("has_audio"):
        cmd += ["-map", "0:a:0"]
    cmd += ["-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-profile:v", "high",
            "-pix_fmt", "yuv420p"]
    if force_bitrate:
        # 码率不足或体积超限时改固定码率，minrate 保证稳过 516k 下限
        cmd += ["-b:v", f"{force_bitrate}", "-minrate", "600k",
                "-maxrate", f"{int(force_bitrate * 1.5)}",
                "-bufsize", f"{force_bitrate * 3}"]
    else:
        cmd += ["-crf", str(crf)]
    if info.get("has_audio"):
        cmd += ["-c:a", "copy"]
    cmd += ["-movflags", "+faststart", str(dst)]

    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        detail = (r.stderr or "").strip().splitlines()
        return False, detail[-1][:200] if detail else f"ffmpeg 退出码 {r.returncode}"
    return True, ""


def verify(dst: Path, target: tuple[int, int], src_dur: float) -> tuple[bool, str]:
    """成品必须能读、尺寸对、时长没缩水、码率达下限，缺一不可。"""
    info = probe(dst)
    if not info:
        return False, "成品无法解析"
    if (info["dw"], info["dh"]) != tuple(target):
        return False, f"成品尺寸 {info['dw']}x{info['dh']}，期望 {target[0]}x{target[1]}"
    if src_dur > 0:
        got = probe_duration(dst)
        if abs(got - src_dur) > 1.5:
            return False, f"时长 {got:.1f}s 与原片 {src_dur:.1f}s 差太多"
    if info["bitrate"] < MIN_BITRATE:
        return False, f"成品码率仅 {info['bitrate']/1000:.0f}k，低于 516k"
    return True, ""


def process(src: Path, args, info: dict, kind: str, bad: list[str]) -> dict:
    target = pick_target(info, kind)
    vf = build_vf(target)
    tmp = src.with_name(f"{src.stem}.part.mp4")

    # 码率不足或体积超限 → 按体积上限反推码率（留 10% 余量）
    force_br = None
    if info["size"] > MAX_BYTES and info["dur"] > 0:
        force_br = int(MAX_BYTES * 8 / info["dur"] * 0.9)
    elif info["bitrate"] < MIN_BITRATE:
        force_br = 900_000

    t0 = time.time()
    ok, err = run_ffmpeg(src, tmp, vf, info, args.crf, force_br)

    # 音频 copy 失败（少见，比如源音轨不是 AAC）时退回重编码音频
    if not ok and info.get("has_audio") and ("aac" in err.lower() or "audio" in err.lower()):
        ok, err = run_ffmpeg_aac(src, tmp, vf, info, args.crf, force_br)
        if ok:
            err = ""

    if not ok:
        tmp.unlink(missing_ok=True)
        return dict(file=str(src), status="failed", reason=f"转码失败：{err}",
                    target=f"{target[0]}x{target[1]}")

    # 校验全部通过才覆盖原片；不通过就删掉半成品，原视频一动不动
    good, why = verify(tmp, target, info["dur"])
    if not good:
        tmp.unlink(missing_ok=True)
        return dict(file=str(src), status="failed", reason=f"校验未过：{why}",
                    target=f"{target[0]}x{target[1]}")

    os.replace(tmp, src)
    return dict(file=str(src), status="fixed", reason="；".join(bad),
                target=f"{target[0]}x{target[1]}",
                seconds=round(time.time() - t0, 1),
                size_mb=round(src.stat().st_size / 1048576, 1))


def run_ffmpeg_aac(src: Path, dst: Path, vf: str, info: dict,
                   crf: int, force_br: int | None) -> tuple[bool, str]:
    cmd = [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), "-map", "0:v:0", "-map", "0:a:0",
           "-vf", vf, "-c:v", "libx264", "-preset", "medium",
           "-profile:v", "high", "-pix_fmt", "yuv420p"]
    cmd += (["-b:v", str(force_br), "-minrate", "600k",
             "-maxrate", str(int(force_br * 1.5)), "-bufsize", str(force_br * 3)]
            if force_br else ["-crf", str(crf)])
    cmd += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        detail = (r.stderr or "").strip().splitlines()
        return False, detail[-1][:200] if detail else "ffmpeg 失败"
    return True, ""


# ---- 主流程 ---------------------------------------------------------------
def collect(root: Path, include_clean: bool) -> list[Path]:
    """列出待检视频：跳过中间态与派生文件（去水印版等），只处理原片。"""
    files = []
    for p in sorted(root.glob("*/*.mp4")):
        if is_partial(p):
            continue
        if is_derived(p) and not include_clean:
            continue
        files.append(p)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="把视频转成巨量千川素材规格")
    ap.add_argument("--root", default=str(OUT_ROOT), help="待处理目录（默认 带货短视频）")
    ap.add_argument("--dry-run", action="store_true", help="只体检，不改文件")
    ap.add_argument("--force", action="store_true", help="合规的也重新编码（默认跳过）")
    ap.add_argument("--include-clean", action="store_true", help="也处理 _去水印版")
    ap.add_argument("--crf", type=int, default=18, help="x264 质量（默认 18，越小越清晰）")
    ap.add_argument("--jobs", type=int, default=4, help="并发转码数（默认 4）")
    args = ap.parse_args()

    for exe in (FFMPEG, FFPROBE):
        if not exe.exists():
            print(f"✗ 缺 {exe.name}，先跑 video-cleaner/setup_env.py")
            return 2

    root = Path(args.root)
    if not root.is_dir():
        print(f"✗ 目录不存在：{root}")
        return 2

    files = collect(root, args.include_clean)
    print(f"待检 {len(files)} 个视频（目录：{root}）")
    if args.dry_run:
        print("模式：只体检，不改文件\n")

    # ---- 第一遍：体检，分成 合规 / 需修 / 不可修 ----
    todo, skipped, unfix = [], [], []
    for f in files:
        info = probe(f)
        if not info:
            unfix.append(dict(file=str(f), status="failed", reason="无法解析", target="-"))
            continue
        kind, bad = classify(info)
        if not bad and not args.force:
            skipped.append(f)
            continue
        if unfixable(bad):
            unfix.append(dict(file=str(f), status="unfixable",
                              reason="；".join(bad), target="-"))
            continue
        todo.append((f, info, kind, bad))

    print(f"本就合规 {len(skipped)} 个 / 需统一 {len(todo)} 个 / 无法修复 {len(unfix)} 个")

    if skipped and (args.dry_run or args.force is False):
        print("\n--- 已合规，不动 ---")
        for f in skipped[:12]:
            print(f"  ✓ {f.parent.name[:26]}/{f.name}")
        if len(skipped) > 12:
            print(f"  …… 另有 {len(skipped) - 12} 个")

    if todo:
        print("\n--- 需统一为千川规格 ---")
        for f, info, kind, bad in todo:
            t = pick_target(info, kind)
            print(f"  · {f.name}  {info['dw']}x{info['dh']} → {t[0]}x{t[1]}")
            print(f"      {'；'.join(bad)}")

    if unfix:
        print("\n--- 无法修复（需人工处理）---")
        for r in unfix:
            print(f"  ✗ {Path(r['file']).name}  {r['reason']}")

    if args.dry_run or not todo:
        if args.dry_run:
            print("\n（--dry-run，未改动任何文件）")
        return 0

    # ---- 第二遍：并发转码 ----
    print(f"\n开始转码，{args.jobs} 并发……")
    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(process, f, args, info, kind, bad): f
                for f, info, kind, bad in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            src = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = dict(file=str(src), status="failed", reason=f"异常：{e}", target="-")
            results.append(r)
            mark = {"fixed": "✓", "failed": "✗"}.get(r["status"], "?")
            extra = f" {r.get('seconds')}s {r.get('size_mb')}M" if r["status"] == "fixed" else ""
            print(f"  [{i}/{len(todo)}] {mark} {src.name}{extra}")
            if r["status"] == "failed":
                print(f"        {r['reason']}")

    elapsed = time.time() - t0
    fixed = [r for r in results if r["status"] == "fixed"]
    failed = [r for r in results if r["status"] == "failed"]

    report = dict(generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                  root=str(root), skipped=[str(f) for f in skipped],
                  fixed=fixed, failed=failed, unfixable=unfix)
    rp = root / "_千川清单.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 56}")
    print(f"完成：统一 {len(fixed)} 个，失败 {len(failed)} 个，"
          f"本就合规 {len(skipped)} 个，无法修复 {len(unfix)} 个")
    print(f"耗时 {elapsed/60:.1f} 分钟")
    print("处理方式：原地替换，文件名不变（原片已被合规版本覆盖）")
    print(f"清单：{rp}")
    print(f"{'=' * 56}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
