#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从抖店罗盘「商品榜单 · 短视频榜」抓取每个商品的带货短视频直链。

数据来源：页面里「晓风运营插件」注入的 <td><p itemid=... title=... videourls="[...]">
不用逐个点开商品，直接从 DOM 属性取，200 条商品只需翻 20 页。

用法：
    python fetch_rank.py                 # 抓全部页
    python fetch_rank.py --max-pages 2   # 只抓前 2 页（调试）
"""
import argparse
import html
import importlib.util
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "compass_video_rank", os.path.join(_here, "compass_video_rank.py"))
cvr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvr)

PAGE = 0          # 0 = 自动从标签页里找榜单页（页面 id 每次运行都会变，不能写死）
OUT_JSON = os.path.join(_here, "..", "商品数据", "短视频榜单_抓取.json")


def eval_full(sess, page, js):
    """执行 JS 并拿到**完整**结果（MCP 只回传前 5000 字节，其余落盘）。"""
    out = sess.call("evaluate", {"page": page, "func": js})
    if "saved to:" in out:
        p = out.split("saved to:", 1)[1].strip()
        p = p.replace("\\\\?\\", "").replace("\\\\?", "")
        try:
            raw = open(p, encoding="utf-8", errors="replace").read()
        except OSError as e:
            raise RuntimeError(f"读取 evaluate 落盘文件失败: {p} ({e})")
    else:
        raw = out
    keep = []
    for line in raw.split("\n"):
        s = line.strip()
        if s.startswith("[UNTRUSTED") or s.startswith("[END_UNTRUSTED"):
            continue
        if s.startswith("Untrusted page content follows"):
            continue
        if s.startswith("Evaluate result truncated"):
            continue
        if s:
            keep.append(line)
    return "\n".join(keep)


JS_ROWS = r'''() => {
  const rows = [...document.querySelectorAll("tbody tr")];
  const lines = [];
  for (let r = 1; r < rows.length; r++) {
    const p = rows[r].querySelector("td p[itemid]");
    if (!p) continue;
    lines.push([
      p.getAttribute("itemid") || "",
      encodeURIComponent(p.getAttribute("title") || ""),
      encodeURIComponent(p.getAttribute("price") || ""),
      encodeURIComponent(p.getAttribute("price2") || ""),
      encodeURIComponent(p.getAttribute("label") || ""),
      encodeURIComponent(p.getAttribute("videourls") || ""),
      encodeURIComponent(p.getAttribute("pic") || "")
    ].join("|"));
  }
  const act = document.querySelector("[class*='pagination'] [class*='active'], [class*='Pagination'] [class*='active']");
  return lines.join("\n") + "\n#PAGE#" + (act ? act.textContent.trim() : "");
}'''


def parse_rows(text):
    items, cur_page = [], None
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#PAGE#"):
            cur_page = line[6:].strip()
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        itemid, t, p1, p2, label, vr = parts[:6]
        pic = parts[6] if len(parts) > 6 else ""
        title = urllib.parse.unquote(t)
        vraw = urllib.parse.unquote(vr)
        videos = []
        aigc = 0
        if vraw:
            try:
                arr = json.loads(html.unescape(vraw))
                if isinstance(arr, str):
                    arr = [arr]
                # 页面数据里会把 AIGC 视频的类型标记（"aigc"）和真实直链混在同一个
                # 数组里。只留 http(s) 直链，AIGC 视频没有可直接下载的直链，单独计数。
                kept = []
                for u in arr:
                    if not isinstance(u, str):
                        continue
                    u = u.replace("&amp;", "&").strip()
                    if u.lower().startswith(("http://", "https://")):
                        kept.append(u)
                    elif u.lower() == "aigc":
                        aigc += 1
                videos = kept
            except Exception:
                videos = [m.replace("&amp;", "&")
                          for m in re.findall(r"https?://[^\"\]\s]+", vraw)]
        items.append(dict(itemid=itemid, title=title.strip(),
                          price=urllib.parse.unquote(p1), price2=urllib.parse.unquote(p2),
                          label=urllib.parse.unquote(label), pic=urllib.parse.unquote(pic),
                          videos=videos, aigc=aigc, page=cur_page))
    return items, cur_page


def click_page(sess, page, num):
    """点分页数字。用 DOM click（插件已验证对这类组件有效）。"""
    js = (r'''() => {
      const want = "%s";
      const els = [...document.querySelectorAll("[class*='agination'] li, [class*='agination'] span, [class*='agination'] a, [class*='agination'] div")];
      const el = els.find(e => (e.textContent || "").trim() === want);
      if (!el) return "NOTFOUND";
      el.click();
      return "OK";
    }''' % num)
    return sess.call("evaluate", {"page": page, "func": js})[-40:]


def find_rank_page(sess, want="rank-product"):
    """从当前标签页里找出罗盘榜单页的 id。

    页面 id 每次打开都会变（昨天是 164，今天可能是 231），绝不能写死；
    找不到就明确报错，让调用方先跑 compass_video_rank.py。
    """
    try:
        text = sess.call("tabs", {"action": "list"})
    except RuntimeError as e:
        raise RuntimeError(f"无法列出标签页: {str(e)[:120]}")
    hits = []
    for line in text.split("\n"):
        m = re.match(r"\[(\d+)\]\s+(\S*compass\.jinritemai\.com\S*)", line.strip())
        if m:
            pid, url = int(m.group(1)), m.group(2)
            if want in url:
                hits.append((pid, url))
    if not hits:
        return None
    pid, url = hits[-1]
    print(f"自动发现榜单页: [{pid}] {url[:80]}")
    return pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=25)
    ap.add_argument("--page", type=int, default=PAGE, help="页面 id，0 表示自动查找")
    args = ap.parse_args()

    sess = cvr.RobustSession().connect()
    try:
        sess.call("name_session", {"name": "fetch-rank-videos"})
    except RuntimeError:
        pass

    page = args.page
    if not page:
        try:
            page = find_rank_page(sess)
        except RuntimeError as e:
            print(f"✗ {e}")
            return 2
        if not page:
            print("✗ 没找到罗盘榜单页（URL 含 rank-product）。")
            print("  请先运行 compass_video_rank.py 打开短视频榜单页，再重跑本脚本。")
            return 2

    all_items, seen = [], set()

    # 回到第 1 页，避免上次运行停留在中间页
    click_page(sess, page, "1")
    time.sleep(3)

    for pno in range(1, args.max_pages + 1):
        text = eval_full(sess, page, JS_ROWS)
        items, cur = parse_rows(text)
        new = 0
        for it in items:
            if it["itemid"] in seen:
                continue
            seen.add(it["itemid"])
            it["rank"] = len(all_items) + 1
            all_items.append(it)
            new += 1
        nv = sum(len(i["videos"]) for i in items)
        print(f"第 {pno} 页（页面标注 {cur}）: {len(items)} 商品 / {nv} 视频，新增 {new}，累计 {len(all_items)}",
              flush=True)
        if new == 0:
            print("  页面未变化，可能已到末页，停止")
            break

        # 翻页
        nxt = str(int(cur) + 1) if cur and cur.isdigit() else str(pno + 1)
        r = click_page(sess, page, nxt)
        print(f"  翻到第 {nxt} 页: {r}", flush=True)
        time.sleep(3.5)

    tot_v = sum(len(i["videos"]) for i in all_items)
    if not all_items:
        print("\n✗ 一个商品都没抓到，按下面顺序排查：")
        print("  1) 晓风运营插件是否加载 —— 未打包扩展在浏览器重启后常丢失，")
        print("     表现为页面有数据但 <td p[itemid]> 不存在。")
        print("     修复：powershell -ExecutionPolicy Bypass -File scripts\\fix_extension.ps1")
        print("           然后 python scripts\\reload_page.py 刷新页面")
        print("     自检：python scripts\\probe_page.py  ，看 itemPers 是否 > 0")
        print("  2) 页面是否在「短视频榜」tab（跑 compass_video_rank.py 会切过去）")
        print("  3) 页面是否登录失效")
        return 3
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump({"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "count": len(all_items), "video_count": tot_v, "items": all_items},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n共 {len(all_items)} 个商品，{tot_v} 个视频")
    print(f"已保存: {os.path.abspath(OUT_JSON)}")


if __name__ == "__main__":
    main()
