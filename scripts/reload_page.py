#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新罗盘页面（让后加载的扩展能注入 content script）。"""
import importlib.util
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "compass_video_rank", os.path.join(HERE, "compass_video_rank.py"))
cvr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cvr)


def main():
    sess = cvr.RobustSession().connect()
    text = sess.call("tabs", {"action": "list"})
    pages = []
    for line in text.split("\n"):
        m = re.match(r"\[(\d+)\]\s+(\S*compass\.jinritemai\.com\S*)", line.strip())
        if m:
            pages.append(int(m.group(1)))
    if not pages:
        print("没有罗盘页面")
        return 1
    pid = pages[-1]
    print(f"刷新页面 {pid} ...")
    sess.call("evaluate", {"page": pid, "func": "() => { location.reload(); return 1; }"})
    time.sleep(8)
    print("已刷新，等待 8 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
