#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
删除本地已下载的带货短视频（清空 D:\\Data\\DouDian\\带货短视频 目录）。

删除范围：该目录下所有 mp4 与商品子文件夹（含 _test、清单 JSON）。
用户说「删除本地带货短视频」时直接执行本脚本，**不需要二次确认，不要只给预览**。

真实实现在 D:\\Data\\DouDian\\scripts\\clean_output.py，本文件只做转发。

用法：
    python clean_output.py --yes                    # 直接删除
    python clean_output.py --yes --keep-clean       # 只删原片，保留 *_clean.mp4
    python clean_output.py                          # 仅预览（不带 --yes 不会删）
"""
import subprocess
import sys

REAL = r"D:\Data\DouDian\scripts\clean_output.py"

if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, REAL] + sys.argv[1:]).returncode)
