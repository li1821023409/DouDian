#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量下载抖音带货榜短视频 + 自动去水印（整条流水线）。

它做什么：打开罗盘短视频榜 → 抓商品视频直链 → 按商品名建文件夹下载 → 批量去水印。

真实实现在 D:\\Data\\DouDian\\scripts\\run_pipeline.py，本文件只做转发，
参数与真实脚本完全一致。

常用用法：
    python run_pipeline.py --from 10 --to 15     # 下载第 10-15 名
    python run_pipeline.py --top 10              # 下载前 10 名
    python run_pipeline.py --from 10 --to 15 --no-clean    # 只下载，不去水印
    python run_pipeline.py --top 10 --replace    # 去水印后删除原片
    python run_pipeline.py --top 3 --dry-run     # 只打印计划，不执行

其他参数：--skip-open（页面已开）--skip-fetch（复用已抓数据）--clean（先清空目录）
         --shards N（去水印并行进程数，默认 2）--workers N（下载并发，默认 6）
"""
import subprocess
import sys

REAL = r"D:\Data\DouDian\scripts\run_pipeline.py"

if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, REAL] + sys.argv[1:]).returncode)
