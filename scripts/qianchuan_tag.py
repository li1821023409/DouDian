#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""巨量千川 · 按商品名建标签并给视频打标签

对应人工流程：
    抖店后台 → 巨量千川 → 工具 → 素材管理 → **标签管理 → 新建标签**
    → 回到 **视频库** → 勾选该商品的视频 → 批量「添加标签」→ 勾上对应标签 → 确认

标签名 = 本地商品文件夹名（也就是下载时的商品名），
文件名前缀同样是它，所以「文件夹 → 视频 → 标签」三者天然对齐。

⚠️ 千川限制：标签名**最多 10 个字**（超了「确定」直接禁用，提示
「标签名称不能超过10个字」）。商品全名往往 20-40 字，所以按前 10 个字截断，
截断后若多个商品撞名会在开头给出警告（它们会被打成同一个标签）。

用法
----
    python scripts/qianchuan_tag.py --dry-run     # 只打印计划：建哪些标签、打哪些视频
    python scripts/qianchuan_tag.py               # 建缺失的标签 + 给库里的视频打标签
    python scripts/qianchuan_tag.py --only 欧尼小花   # 只处理文件夹名含该关键字的商品
    python scripts/qianchuan_tag.py --check        # 只看库里现有标签
"""
import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(r"D:\Data\DouDian")
ROOT = PROJ / "带货短视频"
SCRIPTS = PROJ / "scripts"
LIB_URL = "https://qianchuan.jinritemai.com/tools/creative-management/video-library"
TAG_URL = "https://qianchuan.jinritemai.com/tools/creative-management/tag-library"
REPORT = ROOT / "_千川标签清单.json"

PAGE_SIZE = 20        # 视频库每页 20 条
TAG_CAP = 10          # 单次批量「添加标签」上限（弹窗写 已选 0/10）
# 千川硬限制：标签名**最多 10 个字**（超了「确定」直接禁用，
# 弹窗提示「标签名称不能超过10个字」）。所以标签名 = 商品名前 N 个字。
TAG_NAME_MAX = 10


def _load_qc():
    """复用 qianchuan_upload.py 里的会话/定位/翻页/弹窗处理。"""
    path = SCRIPTS / "qianchuan_upload.py"
    spec = importlib.util.spec_from_file_location("qianchuan_upload", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qc = _load_qc()


def ev(sess, page: int, code: str) -> str:
    """跑一段页面 JS（evaluate 的 `code` 形式，用 return 取值）。

    走 `code` 而不是 `func`：这个 MCP 的 evaluate 不能传参，
    需要把字符串/数组直接拼进代码体里。
    """
    out = sess.call("evaluate", {"page": page, "code": code})
    keep = [ln for ln in out.split("\n")
            if not ln.startswith("[UNTRUSTED") and not ln.startswith("[END_UNTRUSTED")]
    return "\n".join(keep).strip()


def L(v) -> str:
    """Python 值 → JS 字面量。"""
    return json.dumps(v, ensure_ascii=False)


# --------------------------------------------------------------------------
# 标签管理页
# --------------------------------------------------------------------------
READ_TAGS_CODE = r"""
const rows = [...document.querySelectorAll("tbody tr")].map(r => {
  const t = (r.innerText || "").replace(/\s+/g, " ").trim();
  const m = t.match(/^(.+?)\s+2\d{3}-\d{2}-\d{2}/);
  return m ? m[1].trim() : null;
}).filter(Boolean);
return JSON.stringify({tags: rows, count: rows.length});
"""

OPEN_NEW_TAG_CODE = r"""
const b = [...document.querySelectorAll("button")]
  .filter(x => (x.innerText || "").trim() === "新建标签")[0];
if (!b) return "no-btn";
b.click();
return "ok";
"""

FILL_TAG_CODE = r"""
const name = __NAME__;
const lay = [...document.querySelectorAll("[class*=modal],[class*=Modal],[class*=dialog],[class*=Dialog]")]
  .filter(e => e.getBoundingClientRect().height > 80)
  .sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height)[0];
if (!lay) return "no-dialog";
const el = lay.querySelector("input");
if (!el) return "no-input";
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
setter.call(el, name);
el.dispatchEvent(new Event("input", {bubbles: true}));
el.dispatchEvent(new Event("change", {bubbles: true}));
return "filled:" + el.value.length;
"""

SUBMIT_TAG_CODE = r"""
const lay = [...document.querySelectorAll("[class*=modal],[class*=Modal],[class*=dialog],[class*=Dialog]")]
  .filter(e => e.getBoundingClientRect().height > 80)
  .sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height)[0];
if (!lay) return "no-dialog";
const b = [...lay.querySelectorAll("button")].filter(x => (x.innerText || "").trim() === "确定")[0];
if (!b) return "no-btn";
if (b.disabled) return "disabled";
b.click();
return "ok";
"""

CLOSE_MODAL_CODE = r"""
const lay = [...document.querySelectorAll("[class*=modal],[class*=Modal],[class*=dialog],[class*=Dialog]")]
  .filter(e => e.getBoundingClientRect().height > 80)[0];
if (!lay) return "none";
const b = [...lay.querySelectorAll("button")].filter(x => (x.innerText || "").trim() === "取消")[0];
if (b) { b.click(); return "closed"; }
return "no-cancel";
"""

MODAL_TEXT_CODE = r"""
const lay = [...document.querySelectorAll("[class*=modal],[class*=Modal],[class*=dialog],[class*=Dialog]")]
  .filter(e => e.getBoundingClientRect().height > 80)[0];
if (!lay) return "";
return (lay.innerText || "").replace(/\s+/g, " ").slice(0, 160);
"""


def goto_menu(sess, page: int, label: str, url: str, key: str, wait: float = 3.5) -> None:
    """点左侧菜单进某个子页；点不动就直接导航兜底。"""
    ev(sess, page, f"""
const li = [...document.querySelectorAll("li")]
  .filter(e => (e.innerText || "").trim() === {L(label)})[0];
if (li) {{ li.click(); return "menu"; }}
return "no-menu";
""")
    time.sleep(wait)
    href = ev(sess, page, "return location.href;") or ""
    if key not in href:
        sess.call("navigate", {"page": page, "url": url})
        time.sleep(wait + 1.5)


def read_tags(sess, page: int, timeout: int = 20) -> list[str]:
    deadline = time.time() + timeout
    prev, last = -1, []
    while time.time() < deadline:
        try:
            d = json.loads(ev(sess, page, READ_TAGS_CODE))
        except json.JSONDecodeError:
            time.sleep(1)
            continue
        tags = d.get("tags") or []
        if tags and len(tags) == prev:
            return tags
        prev, last = len(tags), tags
        time.sleep(1.2)
    return last


def create_tag(sess, page: int, name: str) -> bool:
    """在标签管理页新建标签；已存在由调用方先挡掉。"""
    if ev(sess, page, OPEN_NEW_TAG_CODE) != "ok":
        print("  ✗ 找不到「新建标签」按钮")
        return False
    time.sleep(1.5)
    r = ev(sess, page, FILL_TAG_CODE.replace("__NAME__", L(name)))
    if not r.startswith("filled"):
        print(f"  ✗ 填不进标签名（{r}）")
        ev(sess, page, CLOSE_MODAL_CODE)
        return False
    time.sleep(1.2)
    r = ev(sess, page, SUBMIT_TAG_CODE)
    if r != "ok":
        print(f"  ✗ 提交失败（{r}）：{ev(sess, page, MODAL_TEXT_CODE)[:90]}")
        ev(sess, page, CLOSE_MODAL_CODE)
        return False
    time.sleep(2.5)
    return name in read_tags(sess, page)


# --------------------------------------------------------------------------
# 视频库：勾选 + 批量添加标签
# --------------------------------------------------------------------------
# 勾选必须**一行一次 evaluate**：一次调用里连点多个 checkbox，React 会重渲染整表，
# 后面的点击落在已脱离文档的旧节点上等于没点（实测连点 3 行只选中 1 行；
# 逐次点击则 3 行全中）。这就是最初误判「视频库只能单选」的原因。
CLICK_ROW_CODE = r"""
const r = [...document.querySelectorAll("tbody tr")][__I__];
if (!r) return "no-row";
const b = r.querySelector("input[type=checkbox]");
if (!b) return "no-box";
if (!b.checked) b.click();
return b.checked ? "on" : "off";
"""

ROW_INDEX_CODE = r"""
const want = new Set(__NAMES__);
const out = [];
[...document.querySelectorAll("tbody tr")].forEach((r, i) => {
  const m = (r.innerText || "").match(/([^\s]+\.mp4)/);
  if (m && want.has(m[1])) out.push([i, m[1]]);
});
return JSON.stringify(out);
"""

CHECKED_CODE = r"""
return String([...document.querySelectorAll("tbody tr input[type=checkbox]")].filter(b => b.checked).length);
"""

CLICK_FIRST_CHECKED_CODE = r"""
const b = [...document.querySelectorAll("tbody tr input[type=checkbox]")].filter(x => x.checked)[0];
if (!b) return "none";
b.click();
return "off";
"""

OPEN_BATCH_TAG_CODE = r"""
const b = [...document.querySelectorAll("button")]
  .filter(x => (x.innerText || "").trim() === "添加标签" && x.getBoundingClientRect().width > 0)[0];
if (!b) return "no-btn";
if (b.disabled) return "disabled";
b.click();
return "ok";
"""

BATCH_MODAL_CODE = r"""
const lay = [...document.querySelectorAll("[class*=modal],[class*=Modal],[class*=dialog],[class*=Dialog]")]
  .filter(e => e.getBoundingClientRect().height > 80)
  .sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height)[0];
if (!lay) return JSON.stringify({open: false});
const t = (lay.innerText || "").replace(/\s+/g, " ");
// 整个文档里找「已选择 N 个视频」：单选时这行不出现（改成「素材名称」了）
const body = (document.body.innerText || "").replace(/\s+/g, " ");
const mv = body.match(/已选择\s*(\d+)\s*个视频/);
const mt = t.match(/已选\s*\((\d+)\s*\/\s*(\d+)\)/);
const skip = new Set(["标签列表", "标签管理", "选择标签"]);
const tags = [...lay.querySelectorAll("li,label")]
  .map(l => (l.innerText || "").trim())
  .filter(x => x && !skip.has(x));
return JSON.stringify({open: true, videos: Number(mv ? mv[1] : 0),
                       selected: Number(mt ? mt[1] : 0), cap: Number(mt ? mt[2] : 0),
                       tags: [...new Set(tags)], text: t.slice(0, 160)});
"""

TICK_TAG_CODE = r"""
const tag = __TAG__;
const lay = [...document.querySelectorAll("[class*=modal],[class*=Modal],[class*=dialog],[class*=Dialog]")]
  .filter(e => e.getBoundingClientRect().height > 80)
  .sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height)[0];
if (!lay) return "no-dialog";
// 标签项一般在弹窗里；但弹层有可能挂在 modal 之外（cascader 的 popper），
// 所以先在弹窗内找，找不到再全文档找可见项。
const pick = (root) => [...root.querySelectorAll("li,label")]
  .filter(l => (l.innerText || "").trim() === tag && l.getBoundingClientRect().width > 0)[0];
let item = pick(lay) || pick(document);
if (!item) return "no-tag";
if (item.tagName === "LI") {
  const lab = item.querySelector("label");
  if (lab) item = lab;
}
const box = item.querySelector("input[type=checkbox]") || item;
if (box.type === "checkbox" && !box.checked) box.click();
const ok = box.type === "checkbox" ? box.checked : true;
return ok ? "checked" : "unchecked";
"""

CONFIRM_BATCH_CODE = r"""
const lay = [...document.querySelectorAll("[class*=modal],[class*=Modal],[class*=dialog],[class*=Dialog]")]
  .filter(e => e.getBoundingClientRect().height > 80)
  .sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height)[0];
if (!lay) return "no-dialog";
const b = [...lay.querySelectorAll("button")].filter(x => (x.innerText || "").trim() === "确认")[0];
if (!b) return "no-btn";
if (b.disabled) return "disabled";
b.click();
return "ok";
"""

BATCH_TAG_CELL_CODE = r"""
const want = new Set(__NAMES__);
const ths = [...document.querySelectorAll("thead th")].map(t => (t.innerText || "").trim());
const idx = ths.indexOf("标签");
const out = {};
[...document.querySelectorAll("tbody tr")].forEach(r => {
  const m = (r.innerText || "").match(/([^\s]+\.mp4)/);
  if (!m || !want.has(m[1])) return;
  const tds = [...r.querySelectorAll("td")];
  const cell = idx >= 0 && tds[idx] ? (tds[idx].innerText || "").replace(/\s+/g, " ").trim() : "";
  out[m[1]] = out[m[1]] ? out[m[1]] + "||" + cell : cell;
});
return JSON.stringify(out);
"""


def checked_count(sess, page: int) -> int:
    return int((ev(sess, page, CHECKED_CODE) or "0").strip() or 0)


def clear_selection(sess, page: int) -> int:
    """逐个取消勾选（一次点多个会打在失效节点上）。"""
    n = 0
    for _ in range(60):
        if not checked_count(sess, page):
            break
        ev(sess, page, CLICK_FIRST_CHECKED_CODE)
        time.sleep(0.45)
        n += 1
    return n


def select_on_page(sess, page: int, files: list[str]) -> int:
    """勾选当前页里属于 files 的行，返回实际勾上的行数。"""
    raw = ev(sess, page, ROW_INDEX_CODE.replace("__NAMES__", L(files))) or "[]"
    try:
        pairs = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    hit = 0
    for idx, fname in pairs:
        for _ in range(2):
            r = ev(sess, page, CLICK_ROW_CODE.replace("__I__", str(idx)))
            if r == "on":
                hit += 1
                break
            time.sleep(0.4)
        time.sleep(0.55)
    return hit


def tag_cells(sess, page: int, names: list[str], tries: int = 5) -> dict[str, str]:
    """读每行的「标签」列文字。

    ⚠️ 不能用「整行文本里出现标签名」来判断：标签名是商品名前 10 字，
    正好是文件名的前缀，整行文本必然包含它，会假阳性。
    必须按表头定位「标签」列，只读那一格。

    刚 reload 完页面可能还没渲染好（返回空串/报错文本），所以取 JSON 片段重试。
    """
    code = BATCH_TAG_CELL_CODE.replace("__NAMES__", L(names))
    for _ in range(tries):
        raw = ev(sess, page, code) or ""
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(raw[i:j + 1])
            except json.JSONDecodeError:
                pass
        time.sleep(1.5)
    return {}


def page_names(sess, page: int) -> list[str]:
    return (qc.read_stable(sess, page) or {}).get("names") or []


def goto_file_page(sess, page: int, fname: str, max_pages: int = 10):
    """翻到该文件所在的页，返回页码或 None。"""
    qc.goto_page(sess, page, 1)
    time.sleep(2)
    pageno = 1
    while pageno <= max_pages:
        names = page_names(sess, page)
        if fname in names:
            return pageno
        if len(names) < PAGE_SIZE:
            return None
        if qc.goto_page(sess, page, pageno + 1) != "ok":
            return None
        pageno += 1
        time.sleep(2.5)
    return None


def apply_batch(sess, page: int, files: list[str], tag: str) -> tuple[str, int]:
    """勾选当前页命中的 files → 添加标签 → 确认。返回 (状态, 实际作用视频数)。"""
    clear_selection(sess, page)
    hit = select_on_page(sess, page, files)
    if not hit:
        return "not-on-page", 0

    r = ev(sess, page, OPEN_BATCH_TAG_CODE)
    if r != "ok":
        return f"open-fail:{r}", 0
    time.sleep(2.2)

    st = json.loads(ev(sess, page, BATCH_MODAL_CODE))
    if not st.get("open"):
        return "no-modal", 0
    if tag not in st.get("tags", []):
        # 标签面板可能是异步加载的：等一会再看一次
        time.sleep(1.5)
        st = json.loads(ev(sess, page, BATCH_MODAL_CODE))
        if tag not in st.get("tags", []):
            print(f"    ⚠ 弹窗里没找到标签「{tag}」，现有：{st.get('tags')}")
            print(f"      弹窗文本：{st.get('text', '')[:100]}")
            ev(sess, page, CLOSE_MODAL_CODE)
            return "tag-missing", 0
    videos = int(st.get("videos") or 0)

    r = ev(sess, page, TICK_TAG_CODE.replace("__TAG__", L(tag)))
    if r != "checked":
        ev(sess, page, CLOSE_MODAL_CODE)
        return f"tick-tag-fail:{r}", 0

    r = ev(sess, page, CONFIRM_BATCH_CODE)
    if r != "ok":
        ev(sess, page, CLOSE_MODAL_CODE)
        return f"confirm-fail:{r}", 0
    time.sleep(3)
    clear_selection(sess, page)
    return "ok", videos


def tag_one(sess, page: int, fname: str, tag: str) -> str:
    """单条兜底：翻到该文件所在页，只勾它，再批量添加标签。"""
    if goto_file_page(sess, page, fname) is None:
        return "not-found"
    r, n = apply_batch(sess, page, [fname], tag)
    return r if r != "ok" or n else "not-applied"


def reload_library(sess, page: int, wait: float = 7.0) -> None:
    """提交后表格不会自己刷新，必须重新加载才读得到新的标签列。"""
    url = (ev(sess, page, "return location.href;") or LIB_URL).strip().strip('"')
    sess.call("navigate", {"page": page, "url": url if url.startswith("http") else LIB_URL})
    time.sleep(wait)


def verify_files(sess, page: int, files: list[str], tag: str) -> dict[str, str]:
    """刷新后逐页回读「标签」列，返回 {文件: 该列文字}。"""
    reload_library(sess, page)
    cells: dict[str, str] = {}
    qc.goto_page(sess, page, 1)
    time.sleep(2)
    pageno = 1
    while pageno <= 10:
        cells.update(tag_cells(sess, page, files))
        if all(tag in (cells.get(f) or "") for f in files):
            break
        if len(page_names(sess, page)) < PAGE_SIZE:
            break
        if qc.goto_page(sess, page, pageno + 1) != "ok":
            break
        pageno += 1
        time.sleep(2.5)
    return cells


def tag_files(sess, page: int, files: list[str], tag: str, verbose=True) -> list[dict]:
    """给一个商品的所有视频打标签：先按页批量，再对漏掉的逐条补。"""
    bad: list[dict] = []
    qc.goto_page(sess, page, 1)
    time.sleep(2)
    pageno = 1
    while pageno <= 10:
        present = [f for f in files if f in page_names(sess, page)]
        if present:
            r, n = apply_batch(sess, page, present, tag)
            if verbose:
                print(f"  第 {pageno} 页批量：{r}，作用 {n}/{len(present)} 条")
            if r != "ok":
                bad.extend({"file": f, "reason": r} for f in present)
        if len(page_names(sess, page)) < PAGE_SIZE:
            break
        if qc.goto_page(sess, page, pageno + 1) != "ok":
            break
        pageno += 1
        time.sleep(2.5)

    # 回读核对 + 单条补打
    cells = verify_files(sess, page, files, tag)
    missing = [f for f in files if tag not in (cells.get(f) or "")]
    if missing and verbose:
        print(f"  核对后仍缺 {len(missing)} 条，逐条补打")
    for fname in missing:
        r = tag_one(sess, page, fname, tag)
        if verbose:
            print(f"    补：{fname[-9:]}  {r}")
        if r != "ok":
            bad.append({"file": fname, "reason": r})

    if missing:
        cells = verify_files(sess, page, files, tag)
        for fname in missing:
            if tag not in (cells.get(fname) or ""):
                if not any(b["file"] == fname for b in bad):
                    bad.append({"file": fname, "reason": f"标签列未显示（{cells.get(fname, '缺行')}）"})
    return bad


# --------------------------------------------------------------------------
def tag_name(product: str, limit: int = TAG_NAME_MAX) -> str:
    """商品名 → 标签名：千川标签名最多 10 个字，取前 10 个字。"""
    s = re.sub(r"\s+", "", product or "")
    return s[:limit]


def local_products(keyword: str = "") -> dict[str, list[str]]:
    """{商品文件夹名: [视频文件名…]}，只收真正有 mp4 的目录。"""
    out: dict[str, list[str]] = {}
    if not ROOT.is_dir():
        return out
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir():
            continue
        files = [p.name for p in sorted(d.glob("*.mp4"))
                 if not p.name.endswith(".part.mp4")]
        if not files:
            continue
        if keyword and keyword not in d.name:
            continue
        out[d.name] = files
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="按商品名建千川标签并给视频打标签")
    ap.add_argument("--only", default="", help="只处理文件夹名含该关键字的商品")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不动页面")
    ap.add_argument("--check", action="store_true", help="只列库里现有标签")
    ap.add_argument("--skip-tag", action="store_true",
                    help="不重新打标签，只回读核对（标签列已显示即算通过）")
    ap.add_argument("--max-len", type=int, default=TAG_NAME_MAX,
                    help="标签名取商品名前 N 个字（千川硬限制 10，别调大）")
    args = ap.parse_args()

    products = local_products(args.only)
    if not products and not args.check:
        print(f"{ROOT} 里没有可处理的商品文件夹（先下载视频）")
        return 2

    # 商品文件夹名 → 标签名（截断到千川允许的长度）
    plan = {folder: tag_name(folder, args.max_len) for folder in products}
    dup: dict[str, list[str]] = {}
    for folder, tag in plan.items():
        dup.setdefault(tag, []).append(folder)
    clash = {t: fs for t, fs in dup.items() if len(fs) > 1}
    for t, fs in clash.items():
        print(f"⚠ 多个商品截断后同名「{t}」：{'、'.join(x[:16] for x in fs)}"
              f"——这些视频会被打成同一个标签")

    sess = qc.McpSession()
    page = qc.ensure_attached(sess, qc.find_lib_page(sess))

    goto_menu(sess, page, "标签管理", TAG_URL, "tag-library")
    tags = read_tags(sess, page)
    print(f"标签库现有 {len(tags)} 个标签：{'、'.join(tags) if tags else '（空）'}")
    if args.check:
        return 0

    missing = [t for t in dict.fromkeys(plan.values()) if t not in tags]
    print(f"本地商品 {len(plan)} 个｜需新建标签 {len(missing)} 个")
    for folder, tag in plan.items():
        print(f"  [{'＋新建' if tag in missing else '已存在'}] {tag:<10} ← {folder}"
              f"（{len(products[folder])} 个视频）")

    if args.dry_run:
        print("\n[dry-run] 未修改任何标签。")
        return 0

    created = []
    for t in missing:
        if create_tag(sess, page, t):
            created.append(t)
            print(f"  ✓ 已建标签：{t}")
        else:
            print(f"  ✗ 建标签失败：{t}")

    goto_menu(sess, page, "视频库", LIB_URL, "video-library", wait=4.5)
    done, failed = [], []
    for folder, tag in plan.items():
        files = products[folder]
        if tag not in created and tag not in tags:
            failed.append({"tag": tag, "product": folder, "reason": "标签不存在"})
            continue
        print(f"\n打标签：{tag}（{folder}，{len(files)} 个视频）")
        if args.skip_tag:
            print("  [--skip-tag] 跳过打标签，只核对")
            bad = []
        else:
            bad = tag_files(sess, page, files, tag)

        cells = verify_files(sess, page, files, tag)
        landed = [f for f in files if tag in (cells.get(f) or "")]
        if landed:
            done.append({"tag": tag, "product": folder, "videos": len(landed), "files": landed})
        print(f"  核对：{len(landed)}/{len(files)} 行标签列已显示「{tag}」")
        # 以「标签列回读」为唯一真相：过程中报的错只要最后打上了就不算失败
        reasons = {b["file"]: b["reason"] for b in bad}
        for f in files:
            if f not in landed:
                failed.append({"tag": tag, "file": f,
                               "reason": reasons.get(f, f"标签列未显示（{cells.get(f, '缺行')}）")})

    REPORT.write_text(json.dumps({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_tags": created,
        "tagged": done, "failed": failed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 56}")
    print(f"标签打成功 {sum(d['videos'] for d in done)} 个视频 / {len(done)} 个商品，失败 {len(failed)} 条")
    print(f"清单：{REPORT}")
    print(f"{'=' * 56}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
