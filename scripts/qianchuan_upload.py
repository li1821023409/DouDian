#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""巨量千川 · 视频库批量上传

把「带货短视频」下已下载的视频批量传进：
    抖店后台 → 巨量千川 → 工具 → 素材管理 → 视频库 → 上传视频

为什么不能直接用常规点击自动化
------------------------------
千川的上传组件在点「点击上传」的那一刻才 document.createElement("input")，
而这个 input **从未插入 DOM**，直接调用原生 .click() 去弹系统文件对话框。
CDP 的 DOM.setFileInputFiles 只能作用于已挂载节点，所以「点按钮 + upload(ref)」
这套常规组合根本喂不进文件——节点压根不在文档树里，拿不到 ref。

本脚本改写 HTMLInputElement.prototype.click：一旦发现游离的 file input，
就把它挂进上传抽屉（2×2 透明小方块），并吞掉原生 click。
这样既不弹系统对话框，CDP 又能正常 setFileInputFiles，页面原有的
onChange 逻辑照常触发（挂在抽屉内，React 的事件委托能收到）。

用法
----
    python scripts/qianchuan_upload.py --dry-run       # 只列待上传清单
    python scripts/qianchuan_upload.py                 # 上传（库里已有的自动跳过）
    python scripts/qianchuan_upload.py --batch 8       # 每批 8 个（默认 6）
    python scripts/qianchuan_upload.py --check-audit   # 只看审核状态，不上传
    python scripts/qianchuan_upload.py --force         # 同名也重传

产物：`带货短视频/_千川上传清单.json`
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(r"D:\Data\DouDian")
ROOT = PROJ / "带货短视频"
SCRIPTS = PROJ / "scripts"
LIB_PATH = "/tools/creative-management/video-library"
LIB_FALLBACK = "https://qianchuan.jinritemai.com/tools/creative-management/video-library"
REPORT = ROOT / "_千川上传清单.json"


def _load_session_cls():
    """复用 doudian_export.py 的 McpSession（登录态、SSE 解析、重连）。"""
    path = SCRIPTS / "doudian_export.py"
    spec = importlib.util.spec_from_file_location("doudian_export", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.McpSession


McpSession = _load_session_cls()


# --------------------------------------------------------------------------
# 页面侧 JS
# --------------------------------------------------------------------------
# 剥离 MCP 给页面内容套的「不可信」标记
def ev(sess, page: int, js: str) -> str:
    out = sess.call("evaluate", {"page": page, "func": js})
    keep = [ln for ln in out.split("\n")
            if not ln.startswith("[UNTRUSTED") and not ln.startswith("[END_UNTRUSTED")]
    return "\n".join(keep).strip()


HOOK_JS = r"""() => {
  if (window.__qcPatched) return "already";
  window.__qcPatched = true;
  const orig = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    if (this.type === "file" && !this.isConnected) {
      const host = document.querySelector(".ovui-drawer__wrap") || document.body;
      this.classList.add("__qc_input");
      this.id = "__qc_upload_input";
      this.setAttribute("style",
        "position:fixed;left:0;top:0;width:2px;height:2px;opacity:0.02;z-index:1");
      host.appendChild(this);
      return;
    }
    return orig.apply(this, arguments);
  };
  return "patched";
}"""

CLICK_UPLOAD_JS = r"""() => {
  const dw = [...document.querySelectorAll(".ovui-drawer__wrap")]
    .filter(e => e.getBoundingClientRect().width > 0)[0];
  if (!dw) return "no-drawer";
  const el = [...dw.querySelectorAll("span,div,a")].filter(e =>
    e.children.length === 0 && (e.innerText || "").trim() === "点击上传")[0];
  if (!el) return "no-text";
  el.dispatchEvent(new MouseEvent("click",
    {bubbles: true, cancelable: true, view: window}));
  return "clicked";
}"""

DRAWER_JS = r"""() => {
  const dw = [...document.querySelectorAll(".ovui-drawer__wrap")]
    .filter(e => e.getBoundingClientRect().width > 0)[0];
  if (!dw) return JSON.stringify({open: false});
  const rows = [...dw.querySelectorAll("tr")]
    .filter(r => (r.innerText || "").includes(".mp4"));
  const items = rows.map(r => {
    const t = (r.innerText || "").replace(/\s+/g, " ").trim();
    const name = (t.match(/([^\s]+\.mp4)/) || [null, ""])[1];
    const uploading = t.includes("取消上传") || /\d+%/.test(t);
    const bad = !uploading && /(上传失败|失败|审核不通过)/.test(t);
    const pct = (t.match(/(\d+)%/) || [null, ""])[1];
    return {name, uploading, bad, percent: pct, text: t.slice(0, 140)};
  });
  const btn = {};
  [...dw.querySelectorAll("button")].forEach(b => {
    const k = b.innerText.trim();
    if (k) btn[k] = b.disabled;
  });
  const t = (dw.innerText || "").replace(/\s+/g, " ");
  const sel = (t.match(/已选择\s*(\d+)\s*\/\s*(\d+)/) || [null, "", ""]);
  return JSON.stringify({open: true, total: items.length, items, btn,
                         selected: Number(sel[1] || 0), cap: Number(sel[2] || 0)});
}"""

LIB_NAMES_JS = r"""() => {
  const names = [...document.querySelectorAll("tr")].map(r => {
    const m = (r.innerText || "").match(/([^\s]+\.mp4)/);
    return m ? m[1] : null;
  }).filter(Boolean);
  const total = ([...document.querySelectorAll("*")].filter(e =>
    e.children.length === 0 && /共\s*\d+\s*条/.test(e.innerText || ""))
    .map(e => e.innerText)[0] || "");
  return JSON.stringify({names, total});
}"""

# 翻页：视频库列表**每页只有 20 条**，34 条素材就有 2 页。
# 只读第一页会让「库里已有」基准偏小，第 2 页起的老素材会被当成新素材重传。
GOTO_PAGE_JS = r"""() => {
  const pag = document.querySelector(".oc-table-pagination");
  if (!pag) return "no-pagi";
  const cells = [...pag.querySelectorAll("*")].filter(e =>
    e.children.length === 0 && (e.innerText || "").trim() === "__N__");
  if (!cells.length) return "no-page";
  (cells[0].closest("[class*=item]") || cells[0]).click();
  return "ok";
}"""

# 抽屉里表格头的全选框：个别文件上传完成后可能没被自动勾上，提交前补勾
SELECT_ALL_JS = r"""() => {
  const dw = document.querySelector(".ovui-drawer__wrap");
  if (!dw) return "no-drawer";
  const head = dw.querySelector("thead");
  const box = head ? [...head.querySelectorAll("input[type=checkbox]")][0] : null;
  if (!box) return "no-box";
  if (!box.checked) { box.click(); return "checked"; }
  return "already";
}"""

AUDIT_JS = r"""() => {
  const out = [];
  [...document.querySelectorAll("tr")].forEach(r => {
    const t = (r.innerText || "").replace(/\s+/g, " ").trim();
    if (!t.includes(".mp4")) return;
    const name = (t.match(/([^\s]+\.mp4)/) || [null, ""])[1];
    let status = "未知";
    if (t.includes("审核不通过")) status = "审核不通过";
    else if (t.includes("审核通过")) status = "审核通过";
    else if (t.includes("审核中")) status = "审核中";
    else if (/上传中|取消上传|\d+%/.test(t)) status = "上传中";
    out.push({name, status});
  });
  return JSON.stringify(out);
}"""

CLICK_TEXT_JS = r"""(text) => {
  const dw = document.querySelector(".ovui-drawer__wrap") || document;
  const btns = [...dw.querySelectorAll("button")];
  const b = btns.filter(x => x.innerText.trim() === text)[0];
  if (b) { if (!b.disabled) { b.click(); return "clicked"; } return "disabled"; }
  const rows = [...dw.querySelectorAll("tr")].filter(r => (r.innerText || "").includes(".mp4"));
  const last = rows[rows.length - 1];
  if (!last) return "no-row";
  const del = [...last.querySelectorAll("span,div,a,button")]
    .filter(e => e.children.length === 0 && (e.innerText || "").trim() === text)[0];
  if (!del) return "no-el";
  del.dispatchEvent(new MouseEvent("click", {bubbles: true, cancelable: true, view: window}));
  return "clicked-row";
}"""


# --------------------------------------------------------------------------
# 页面定位
# --------------------------------------------------------------------------
def list_tabs(sess) -> list[tuple[int, str]]:
    try:
        text = sess.call("tabs", {"action": "list"})
    except RuntimeError:
        return []
    out = []
    for line in text.split("\n"):
        m = re.match(r"\[(\d+)\]\s+(\S+)", line.strip())
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


def page_ok(sess, page) -> bool:
    """标签页能不能操作：扩展是否还 attach 着这个 tab 的会话。"""
    try:
        sess.call("snapshot", {"page": page, "mode": "interactive"})
        return True
    except RuntimeError:
        return False


def find_lib_page(sess):
    """优先返回**会话仍在**的那个视频库标签页。

    实测会同时存在多个视频库 tab（自己开的 + 被别的 agent 接管的），
    旧逻辑拿第一个，碰巧是已解绑的那个就直接崩在 snapshot 上。
    """
    cands = [pid for pid, url in list_tabs(sess) if LIB_PATH in url]
    for pid in cands:
        if page_ok(sess, pid):
            return pid
    return cands[0] if cands else None


def ensure_attached(sess, page: int, verbose=True) -> int:
    """确认标签页可操作，必要时把会话重新绑上。

    上一次脚本跑完、或标签被别的 agent 接管后，扩展会解绑该 tab 的会话，
    此时 snapshot 报 `Page N has no attached session`。navigate 一次即可重绑，
    仍不行就新开一个视频库标签页（不刷新已就绪的页面，避免丢当前状态）。
    """
    if page_ok(sess, page):
        return page
    if verbose:
        print(f"page {page} 会话未绑定，重新导航绑定…")
    try:
        sess.call("navigate", {"page": page, "url": LIB_FALLBACK})
        time.sleep(5)
        if page_ok(sess, page):
            return page
    except RuntimeError:
        pass
    if verbose:
        print("重新绑定失败，新开视频库标签页…")
    sess.call("tabs", {"action": "new", "url": LIB_FALLBACK})
    for _ in range(20):
        time.sleep(1.5)
        pid = find_lib_page(sess)
        if pid and page_ok(sess, pid):
            return pid
    raise RuntimeError("视频库页面无法建立会话，请确认浏览器扩展在线且已登录千川")


def open_library(sess, verbose=True) -> int:
    """定位视频库页：复用已开的 → 从抖店首页点「巨量千川」→ 兜底直达。"""
    pid = find_lib_page(sess)
    if pid:
        if verbose:
            print(f"复用已打开的视频库页（page {pid}）")
        return pid

    # 抖店后台首页点「巨量千川」
    fxg = next((p for p, u in list_tabs(sess) if "fxg.jinritemai.com" in u), None)
    if fxg:
        if verbose:
            print("在抖店后台点「巨量千川」…")
        ev(sess, fxg, r"""() => {
          const el = [...document.querySelectorAll("a,span,div")]
            .filter(e => e.children.length === 0 && (e.innerText || "").trim() === "巨量千川")[0];
          if (!el) return "no";
          (el.closest("a") || el).click();
          return "ok";
        }""")
        for _ in range(20):
            time.sleep(1.5)
            pid = find_lib_page(sess)
            if pid:
                if verbose:
                    print(f"已跳转到视频库（page {pid}）")
                return pid

    # 兜底：直达视频库，页面会自动补 aavid
    if verbose:
        print("直接打开视频库页面…")
    tabs = list_tabs(sess)
    pid = tabs[0][0] if tabs else None
    if pid is None:
        raise RuntimeError("浏览器没有可用标签页，请先打开 Chrome 并保持 BrowserOS 扩展在线")
    sess.call("tabs", {"action": "new", "url": LIB_FALLBACK})
    for _ in range(20):
        time.sleep(1.5)
        pid = find_lib_page(sess)
        if pid:
            return pid
    raise RuntimeError("打不开巨量千川视频库，请确认已登录抖店/千川后台")


def dismiss_popups(sess, page: int, verbose=True) -> int:
    """关掉进入千川后可能出现的运营弹窗，避免挡住上传按钮。"""
    closed = 0
    for _ in range(3):
        n = ev(sess, page, r"""() => {
          const boxes = [...document.querySelectorAll(
            "[class*=modal],[class*=Modal],[class*=dialog],[class*=Dialog]")]
            .filter(e => e.getBoundingClientRect().height > 120);
          let n = 0;
          for (const b of boxes) {
            const x = [...b.querySelectorAll("[class*=close],[class*=Close],button")]
              .filter(e => {
                const r = e.getBoundingClientRect();
                return r.width > 0 && (e.className.toString().includes("close")
                  || (e.innerText || "").trim() === "");
              })[0];
            if (x) { x.click(); n++; }
          }
          return String(n);
        }""")
        try:
            k = int(n.strip() or 0)
        except ValueError:
            k = 0
        if not k:
            break
        closed += k
        time.sleep(1.2)
    if closed and verbose:
        print(f"关闭弹窗 {closed} 个")
    return closed


# --------------------------------------------------------------------------
# 库内已有素材（去重基准）
# --------------------------------------------------------------------------
def read_page(sess, page: int):
    """读当前页的素材名 + 共 N 条。解析失败返回 None。"""
    try:
        return json.loads(ev(sess, page, LIB_NAMES_JS))
    except json.JSONDecodeError:
        return None


def goto_page(sess, page: int, n: int) -> str:
    """点分页里的页码 n（1/2/…）。"""
    return ev(sess, page, GOTO_PAGE_JS.replace("__N__", str(n)))


PAGE_SIZE = 20          # 视频库列表每页 20 条（实测）


def read_stable(sess, page: int, tries: int = 8, gap: float = 1.0) -> dict:
    """读当前页，直到行数连续两次一致。

    列表是异步渲染的：切页后的首帧常常只有 9~14 行，直接取会漏素材。
    """
    prev = None
    last = None
    for _ in range(tries):
        d = read_page(sess, page)
        if d:
            last = d
            cur = d.get("names") or []
            if cur and prev is not None and len(cur) == prev:
                return d
            prev = len(cur)
        time.sleep(gap)
    return last or {"names": [], "total": ""}


def library_names(sess, page: int, timeout: int = 90) -> set[str]:
    """读库内已有素材名（**跨页**），作为去重基准。

    三个坑都踩过：
    1. 列表异步渲染，刚进页面就抓会拿到半截（「共 16 条」只读到 9 条）；
    2. 列表每页只有 20 条，只读第一页的话，第 2 页起的老素材会被当成新素材重传；
    3. 上一次调用可能把页面停在末页，所以每次都必须先回第 1 页再读。
    """
    deadline = time.time() + timeout
    names: set[str] = set()
    goto_page(sess, page, 1)
    time.sleep(2)
    pageno = 1
    while time.time() < deadline:
        d = read_stable(sess, page)
        cur = d.get("names") or []
        m = re.search(r"共\s*(\d+)\s*条", d.get("total") or "")
        total = int(m.group(1)) if m else 0
        if not cur:
            time.sleep(1)
            continue
        names |= set(cur)
        if total and len(names) >= total:
            return names
        if len(cur) < PAGE_SIZE:          # 末页
            return names
        if goto_page(sess, page, pageno + 1) != "ok":
            return names
        pageno += 1
        time.sleep(2.5)
    return names


def audit_rows(sess, page: int, timeout: int = 90) -> list[dict]:
    """逐页读审核状态（列表分页，只看第一页会漏掉后面的素材）。"""
    deadline = time.time() + timeout
    rows: list[dict] = []
    goto_page(sess, page, 1)
    time.sleep(2)
    pageno = 1
    while time.time() < deadline:
        read_stable(sess, page)
        try:
            got = json.loads(ev(sess, page, AUDIT_JS) or "[]")
        except json.JSONDecodeError:
            time.sleep(1)
            continue
        if not got:
            time.sleep(1)
            continue
        rows.extend(got)
        d = read_page(sess, page) or {}
        m = re.search(r"共\s*(\d+)\s*条", d.get("total") or "")
        total = int(m.group(1)) if m else 0
        if total and len(rows) >= total:
            return rows
        if len(got) < PAGE_SIZE:
            return rows
        if goto_page(sess, page, pageno + 1) != "ok":
            return rows
        pageno += 1
        time.sleep(2.5)
    return rows


# --------------------------------------------------------------------------
# 上传抽屉
# --------------------------------------------------------------------------
def open_drawer(sess, page: int) -> None:
    """点「上传视频」打开右侧抽屉，已开着就复用。"""
    if json.loads(ev(sess, page, DRAWER_JS)).get("open"):
        return
    r = ev(sess, page, r"""() => {
      const b = [...document.querySelectorAll("button")]
        .filter(x => x.innerText.trim() === "上传视频")[0];
      if (!b) return "no-btn";
      b.click();
      return "clicked";
    }""")
    if r != "clicked":
        raise RuntimeError("找不到「上传视频」按钮，页面可能未加载完成")
    for _ in range(15):
        time.sleep(1)
        if json.loads(ev(sess, page, DRAWER_JS)).get("open"):
            return
    raise RuntimeError("上传抽屉没有打开")


def attach_input(sess, page: int) -> str:
    """装 hook → 点「点击上传」→ 让游离 input 落地 → 返回它的 ref。"""
    ev(sess, page, HOOK_JS)
    # 清掉历史残留，保证改的是本次新建的那个
    ev(sess, page, '() => { document.querySelectorAll(".__qc_input").forEach(e => e.remove()); return "1"; }')
    r = ev(sess, page, CLICK_UPLOAD_JS)
    if r != "clicked":
        raise RuntimeError(f"点不到「点击上传」（返回 {r}）")
    time.sleep(0.8)

    sn = sess.call("snapshot", {"page": page, "mode": "interactive"})
    m = re.search(r'button "选择文件" \[ref=(e\d+)\]', sn)
    if not m:
        sn2 = sess.call("snapshot", {"page": page, "mode": "interactive"})
        m = re.search(r'button "选择文件" \[ref=(e\d+)\]', sn2)
    if not m:
        raise RuntimeError("file input 没挂上，取不到 ref")
    return m.group(1)


def drawer_state(sess, page: int) -> dict:
    return json.loads(ev(sess, page, DRAWER_JS))


def upload_files(sess, page: int, ref: str, files: list[Path]) -> None:
    sess.call("upload", {"page": page, "ref": ref,
                         "files": [str(f) for f in files]})


def wait_batch(sess, page: int, expect: int, timeout: int, verbose=True) -> dict:
    """等本批全部传完（不再出现百分比/取消上传）。"""
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        st = drawer_state(sess, page)
        items = st.get("items", [])
        pending = [i for i in items if i.get("uploading")]
        if verbose:
            done = len(items) - len(pending)
            msg = f"  已传 {done}/{len(items)}（本批目标 {expect}）"
            if msg != last:
                print(msg, end="\r", flush=True)
                last = msg
        if len(items) >= expect and not pending:
            if verbose:
                print()
            return st
        time.sleep(3)
    if verbose:
        print()
    return drawer_state(sess, page)


def confirm(sess, page: int) -> str:
    return ev(sess, page, r"""() => {
      const dw = document.querySelector(".ovui-drawer__wrap");
      if (!dw) return "no-drawer";
      const b = [...dw.querySelectorAll("button")]
        .filter(x => x.innerText.trim() === "确定")[0];
      if (!b) return "no-btn";
      if (b.disabled) return "disabled";
      b.click();
      return "ok";
    }""")


# --------------------------------------------------------------------------
# 任务清单
# --------------------------------------------------------------------------
def collect(root: Path) -> list[Path]:
    files = []
    for p in sorted(root.glob("*/*.mp4")):
        if p.name.endswith(".part.mp4"):
            continue
        files.append(p)
    return files


def run_tagging() -> int:
    """上传完顺手打标签（按商品名建标签 → 给对应视频打上）。

    工作流里只跑 qianchuan_upload.py 一个命令，标签也不会漏；
    不想打标签就加 --no-tag。
    """
    print(f"\n{'=' * 56}\n▶ 按商品打标签（qianchuan_tag.py）\n{'=' * 56}", flush=True)
    return subprocess.run([sys.executable, str(SCRIPTS / "qianchuan_tag.py")],
                          cwd=str(PROJ)).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="巨量千川视频库批量上传")
    ap.add_argument("--root", default=str(ROOT), help="视频根目录")
    ap.add_argument("--batch", type=int, default=6, help="每批上传数量")
    ap.add_argument("--dry-run", action="store_true", help="只列清单，不动手")
    ap.add_argument("--force", action="store_true", help="库里有同名也重传")
    ap.add_argument("--check-audit", action="store_true", help="只看审核状态")
    ap.add_argument("--limit", type=int, default=0, help="只传前 N 个（0=不限）")
    ap.add_argument("--timeout", type=int, default=1800, help="单批等待上限（秒）")
    ap.add_argument("--no-tag", action="store_true",
                    help="上传完不打标签（默认会调用 qianchuan_tag.py 按商品打标签）")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"目录不存在：{root}")
        return 2

    sess = McpSession()
    page = ensure_attached(sess, open_library(sess))
    dismiss_popups(sess, page)
    time.sleep(1.5)

    existing = library_names(sess, page)
    print(f"视频库现有 {len(existing)} 个不同文件名（同名素材已合并计数）")

    if args.check_audit:
        rows = audit_rows(sess, page)
        stat = {}
        for r in rows:
            stat[r["status"]] = stat.get(r["status"], 0) + 1
        print("\n审核状态分布：")
        for k, v in sorted(stat.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
        bad = [r["name"] for r in rows if r["status"] == "审核不通过"]
        if bad:
            print(f"\n审核不通过 {len(bad)} 条：")
            for n in bad:
                print(f"  ✗ {n}")
        return 0

    todo = [p for p in collect(root) if args.force or p.name not in existing]
    skip = len(collect(root)) - len(todo)
    if args.limit:
        todo = todo[:args.limit]

    print(f"本地视频 {len(collect(root))} 个｜库里已有跳过 {skip} 个｜待上传 {len(todo)} 个")
    if not todo:
        print("没有需要上传的视频。")
        if not args.no_tag:
            # 库里已有素材不代表标签打过：这里顺手补一次
            if run_tagging() != 0:
                print("⚠ 打标签失败，可单独重跑：qianchuan_tag.py")
                return 2
        return 0

    total_mb = sum(p.stat().st_size for p in todo) / 1048576
    print(f"待上传体积 {total_mb:.0f} MB，分批 {args.batch} 个\n")

    if args.dry_run:
        for p in todo:
            print(f"  · {p.parent.name}/{p.name}  "
                  f"{p.stat().st_size / 1048576:.0f} MB")
        print("\n[dry-run] 未上传任何文件。")
        return 0

    # 打开抽屉并让 file input 落地
    open_drawer(sess, page)
    attach_input(sess, page)
    print("上传面板就绪\n")

    done, failed = [], []
    t0 = time.time()
    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        idx = i // args.batch + 1
        total_batches = (len(todo) + args.batch - 1) // args.batch
        print(f"[{idx}/{total_batches}] 上传 {len(chunk)} 个："
              f"{chunk[0].name} … {chunk[-1].name}")
        # 每批都必须重新挂载 input：它是一次性的，第一次 change 之后组件就不再
        # 响应（实测往同一个 input 二次投喂，列表一行都不增）。
        ref = attach_input(sess, page)
        try:
            upload_files(sess, page, ref, chunk)
        except RuntimeError as e:
            print(f"  上传调用失败，重建 input：{str(e)[:80]}")
            ref = attach_input(sess, page)
            upload_files(sess, page, ref, chunk)

        st = wait_batch(sess, page, len(done) + len(chunk), args.timeout)
        items = st.get("items", [])
        names = {it["name"] for it in items}
        bad = {it["name"] for it in items if it.get("bad")}
        for f in chunk:
            if f.name in bad:
                failed.append({"file": str(f), "reason": "页面报上传失败"})
            elif f.name in names:
                done.append(f)
            else:
                failed.append({"file": str(f), "reason": "未出现在上传列表"})

    # 提交前：确认所有行都被勾上（个别文件传完后不会自动勾选，未勾的不会被提交）
    st = drawer_state(sess, page)
    if st.get("selected", 0) < st.get("total", 0):
        print(f"勾选 {st.get('selected')}/{st.get('total')}，补勾全选")
        ev(sess, page, SELECT_ALL_JS)
        time.sleep(1)
    time.sleep(2)

    r = confirm(sess, page)
    print(f"\n提交结果：{r}")

    # 提交后回读：以库里真的出现为准，而不是信 confirm 的返回值。
    # 注意提交之后页面**不会自动刷新列表**，必须重新加载才读得到新素材——
    # 否则会把「其实已入库」误判成失败（实测 8 个全成功，不刷新只读到 2 个）。
    time.sleep(3)
    url = (ev(sess, page, "() => location.href") or LIB_FALLBACK).strip().strip('"')
    try:
        sess.call("navigate", {"page": page, "url": url if url.startswith("http") else LIB_FALLBACK})
    except RuntimeError:
        sess.call("navigate", {"page": page, "url": LIB_FALLBACK})
    time.sleep(8)

    after = library_names(sess, page)
    landed = [f for f in done if f.name in after]
    for f in done:
        if f.name not in after:
            failed.append({"file": str(f), "reason": "提交后未出现在视频库"})
    if len(landed) != len(done):
        print(f"核对：{len(done)} 个已提交，库里实际新增 {len(landed)} 个")
    done = landed
    elapsed = time.time() - t0

    REPORT.write_text(json.dumps({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "submitted": len(done), "failed": failed,
        "skipped_existing": skip,
        "elapsed_min": round(elapsed / 60, 1),
        "confirm": r,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 56}")
    print(f"本次提交 {len(done)} 个，失败 {len(failed)} 个，"
          f"耗时 {elapsed / 60:.1f} 分钟")
    print(f"清单：{REPORT}")
    print(f"{'=' * 56}")
    if failed:
        for f in failed[:8]:
            print(f"  ✗ {Path(f['file']).name}：{f['reason']}")

    # 上传完顺手打标签：工作流里只跑这一个脚本，标签也不会漏
    if done and not args.no_tag:
        if run_tagging() != 0:
            print("⚠ 上传成功，但打标签失败（详见上面的输出）。"
                  "可单独重跑：qianchuan_tag.py")
            return 2

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
