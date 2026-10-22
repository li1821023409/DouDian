"""探查数据行：商品名、带货短视频单元格的元素结构。"""
import importlib.util
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
  const out = {totalRows: rows.length, samples: []};

  for (let r = 1; r < Math.min(rows.length, 3); r++) {
    const tds = [...rows[r].children];
    const item = {row: r, cellCount: tds.length};
    // 商品列
    if (tds[1]) {
      const a = tds[1].querySelector("a");
      item.productText = clean(tds[1].textContent).slice(0, 120);
      item.productHref = a ? a.href.slice(0, 160) : null;
      item.productImgs = [...tds[1].querySelectorAll("img")].map(i => i.src.slice(0, 120)).slice(0, 2);
    }
    // 带货短视频列
    if (tds[2]) {
      const cell = tds[2];
      item.videoImgCount = cell.querySelectorAll("img").length;
      item.videoImgs = [...cell.querySelectorAll("img")].map(i => ({
        src: i.src.slice(0, 140), cls: (i.className || "").slice(0, 50)
      })).slice(0, 4);
      // 背景图元素
      item.bgEls = [...cell.querySelectorAll("div")].map(d => {
        const bg = getComputedStyle(d).backgroundImage;
        return bg && bg !== "none" ? bg.slice(0, 140) : null;
      }).filter(Boolean).slice(0, 4);
      item.videoCellHtml = cell.innerHTML
        .replace(/src="data:[^"]*"/g, 'src="data:..."')
        .replace(/style="[^"]*"/g, "")
        .slice(0, 1200);
    }
    out.samples.push(item);
  }
  return JSON.stringify(out);
}'''


def main():
    sess = cvr.RobustSession().connect()
    try:
        sess.call("name_session", {"name": "probe-rank-dom"})
    except RuntimeError:
        pass
    raw = cvr.js_eval(sess, PAGE, JS)
    try:
        data = json.loads(raw)
    except Exception:
        print(raw[:3000])
        return
    print("总行数:", data.get("totalRows"))
    for s in data.get("samples", []):
        print(f"\n===== 数据行 {s['row']} (单元格 {s['cellCount']}) =====")
        print("商品:", s.get("productText"))
        print("链接:", s.get("productHref"))
        print("视频缩略图 img 数:", s.get("videoImgCount"))
        for im in s.get("videoImgs", []):
            print("   img:", im)
        print("背景图:", s.get("bgEls"))
        print("单元格HTML:", (s.get("videoCellHtml") or "")[:700])


if __name__ == "__main__":
    main()
