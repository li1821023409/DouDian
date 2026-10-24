#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查榜单页每行 <p itemid> 上插件实际注入了哪些属性。"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "cvr", os.path.join(HERE, "compass_video_rank.py"))
cvr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cvr)

JS = r'''() => {
  const ps = [...document.querySelectorAll("tbody td p[itemid]")];
  if (!ps.length) return JSON.stringify({count: 0});
  const p = ps[0];
  const attrs = {};
  for (const a of p.attributes) {
    attrs[a.name] = (a.value || "").slice(0, 120);
  }
  // 再看整行里有没有视频相关的元素/属性
  const tr = p.closest("tr");
  const links = [...(tr ? tr.querySelectorAll("a") : [])]
      .map(a => (a.href || "").slice(0, 80)).slice(0, 5);
  return JSON.stringify({
    count: ps.length,
    attrs: attrs,
    text: (p.textContent || "").slice(0, 60),
    rowText: (tr ? tr.innerText : "").replace(/\s+/g, " ").slice(0, 200),
    links: links
  });
}'''


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
    out = sess.call("evaluate", {"page": pid, "func": JS})
    for line in out.split("\n"):
        s = line.strip()
        if s.startswith("{") and '"count"' in s:
            d = json.loads(s)
            print(f"页面 [{pid}]  带 itemid 的元素: {d.get('count')}")
            if d.get("attrs"):
                print("\n第一个元素的属性：")
                for k, v in d["attrs"].items():
                    mark = "  <<<" if "video" in k.lower() else ""
                    print(f"  {k:<14} = {v}{mark}")
                print(f"\n元素文本: {d.get('text')}")
                print(f"整行文本: {d.get('rowText')}")
                print(f"行内链接: {d.get('links')}")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
