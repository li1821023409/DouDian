#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""带货短视频的命名规则——派生文件后缀的唯一事实来源。

为什么单独抽一个模块
    流水线会产出多种派生文件：
        <名>.mp4                  原片（下载器写入，唯一真源）
        <名>_去水印版.mp4          去水印成品
        <名>_千川.mp4              巨量千川规格成品
        <名>.part.mp4             写到一半的中间态（正常结束会改名）
    每个扫描脚本都要判断"这是不是原片"。以前各脚本各自复制一份条件，
    加一个新后缀就得改六七个地方，漏一处就会出现「把成品当原片再处理一遍」。
    2026-10-26 加 _千川 时就遇到了这个情况，于是收敛到这里。

用法
    from video_rules import is_original, is_derived
    files = [p for p in root.glob("*/*.mp4") if is_original(p)]
"""
from pathlib import Path

# 派生后缀：凡是以这些结尾的都不是原片
DERIVED_SUFFIXES = (
    "_去水印版",
    "_clean",   # 旧命名，保留兼容
    "_千川",
)

PART_SUFFIX = ".part.mp4"


def is_derived(p: Path | str) -> bool:
    """是否为流水线产出的派生文件（去水印 / 千川 / 旧版 clean）。"""
    stem = Path(p).stem
    return any(stem.endswith(s) for s in DERIVED_SUFFIXES)


def is_partial(p: Path | str) -> bool:
    """是否为编码中断留下的中间态。"""
    return str(p).endswith(PART_SUFFIX) or Path(p).stem.endswith(".part")


def is_original(p: Path | str) -> bool:
    """是否为可再次加工的原片：mp4、不是中间态、不是任何派生文件。"""
    name = Path(p).name
    if not name.lower().endswith(".mp4"):
        return False
    return not is_partial(p) and not is_derived(p)


if __name__ == "__main__":
    samples = ["a_01.mp4", "a_01_去水印版.mp4", "a_01_千川.mp4",
               "a_01_clean.mp4", "a_01.part.mp4", "a_01_千川.part.mp4", "x.png"]
    for s in samples:
        print(f"{s:<26} 原片={is_original(s)!s:<5} 派生={is_derived(s)!s:<5} 中间态={is_partial(s)}")
