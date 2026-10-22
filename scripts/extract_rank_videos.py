"""从罗盘榜单页提取商品名 + 带货短视频直链（依赖页面里 zzb 插件注入的 p[itemid] 节点）。"""
import importlib.util
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "compass_video_rank", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "compass_video_rank.py"))
cvr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cvr)

PAGE = 164

JS = r'''() => {
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const rows = [...document.querySelectorAll("tbody tr")];
  const items = [];
  for (let r = 1; r < rows.length; r++) {
    const td = rows[r].querySelector("td p[itemid]");
    if (!td) continue;
    items.push({
      itemid: td.getAttribute("itemid"),
      title: td.getAttribute("title"),
      price: td.getAttribute("price"),
      price2: td.getAttribute("price2"),
      label: td.getAttribute("label"),
      pic: (td.getAttribute("pic") || "").slice(0, 120),
      videoRaw: td.getAttribute("videourls") || ""
    });
  }
  const pageNums = [...document.querySelectorAll("[class*='pagination'] li, [class*='Pagination'] li")]
      .map(e => clean(e.textContent)).filter(t => /^\d+$/.test(t));
  const active = document.querySelector("[class*='pagination'] [class*='active'], [class*='Pagination'] [class*='active']");
  const payload = JSON.stringify({items, pageNums: [...new Set(pageNums)], active: active ? clean(active.textContent) : null});
  return btoa(unescape(encodeURIComponent(payload)));
}'''


def parse_videourls(raw):
    if not raw:
        return []
    s = html.unescape(raw)          # &quot; -> "
    try:
        arr = json.loads(s)
        if isinstance(arr, str):
            arr = [arr]
        return [u.replace("&amp;", "&") for u in arr if isinstance(u, str)]
    except Exception:
        # 兜底：正则抓 http 链接
        import re
        return [m.replace("&amp;", "&") for m in re.findall(r"https?://[^\"\]]+", s)]


def main():
    sess = cvr.RobustSession().connect()
    try:
        sess.call("name_session", {"name": "extract-rank"})
    except RuntimeError:
        pass
    raw = cvr.js_eval(sess, PAGE, JS)
    import base64
    import re as _re
    b64 = _re.sub(r"[^A-Za-z0-9+/=]", "", raw)
    data = json.loads(base64.b64decode(b64 + "=" * (-len(b64) % 4)).decode("utf-8"))
    items = data.get("items", [])
    print(f"本页商品 {len(items)} 个，分页 {data.get('pageNums')}，当前页 {data.get('active')}")
    total_v = 0
    for i, it in enumerate(items, 1):
        urls = parse_videourls(it.get("videoRaw"))
        total_v += len(urls)
        t = (it.get("title") or "")[:40]
        print(f"{i:2d}. {t}  视频 {len(urls)} 个")
        if urls:
            u = urls[0]
            print(f"     {u[:150]}")
    print(f"\n本页视频合计 {total_v} 个")
    if items:
        json.dump({"items": [{**it, "videos": parse_videourls(it.get("videoRaw"))}
                             for it in items]},
                  open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "商品数据", "_page_probe.json"), "w",
                       encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已保存样例到 商品数据/_page_probe.json")


if __name__ == "__main__":
    main()
