#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断罗盘榜单页的 DOM 状态：表格行数、插件注入的 itemid 数量、当前 URL。"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "compass_video_rank", os.path.join(HERE, "compass_video_rank.py"))
cvr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cvr)

PROBE = r'''() => {
  const trs = document.querySelectorAll("tbody tr");
  const ps = document.querySelectorAll("tbody td p[itemid]");
  const firstTr = trs[1] ? trs[1].innerText.replace(/\s+/g," ").slice(0, 120) : "";
  const tabs = [...document.querySelectorAll("[class*='tabs-tab']")]
      .map(e => (e.className.includes("active") ? "*" : "") + e.innerText.trim().slice(0,12))
      .slice(0, 10);
  return JSON.stringify({
    url: location.href.slice(0, 100),
    trs: trs.length,
    itemPers: ps.length,
    firstName: firstTr,
    tabs: tabs
  });
}'''


def main():
    sess = cvr.RobustSession().connect()
    text = sess.call("tabs", {"action": "list"})
    pages = []
    for line in text.split("\n"):
        m = re.match(r"\[(\d+)\]\s+(\S*compass\.jinritemai\.com\S*)", line.strip())
        if m:
            pages.append((int(m.group(1)), m.group(2)))
    print("罗盘页面:", pages)
    if not pages:
        print("没有罗盘页面，先跑 compass_video_rank.py")
        return 1
    pid = pages[-1][0]
    out = sess.call("evaluate", {"page": pid, "func": PROBE})
    # 剥掉 untrusted 包裹
    for line in out.split("\n"):
        s = line.strip()
        if s.startswith("{") and "trs" in s:
            print("DOM 状态:", s)
            break
    else:
        print("原始返回:", out[:800])
    return 0


if __name__ == "__main__":
    sys.exit(main())
