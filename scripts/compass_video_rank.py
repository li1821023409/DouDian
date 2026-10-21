#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动进入抖店电商罗盘「短视频榜单」目标页

目标：进入抖店后台 → 电商罗盘市场 → 商品榜单 → 短视频榜
      → 类目（母婴宠物/宠物生活）→ 非知名品牌

设计要点：
- 复用 doudian_export.py 的 McpSession（登录态、SSE 解析、断线重连、页面清理）。
- 榜单页 URL 固定：compass.jinritemai.com/shop/chance/rank-product，
  登录态下直达即可；页面会记住上次的类目选择，但「短视频榜」tab 与
  「非知名品牌」开关需要显式点选，确保每次结果一致。
- 产出方式待定：当前只负责把页面稳定带到目标筛选状态并保留，
  后续可在本脚本上扩展「截图 / 抓取榜单数据 / 导出」。
"""
import importlib.util
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
spec = importlib.util.spec_from_file_location(
    "doudian_export", os.path.join(os.path.dirname(__file__), "doudian_export.py"))
dex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dex)


class RobustSession(dex.McpSession):
    """修复 SSE 多帧解析：扫描全部 data: 帧，按 id 取对应 JSON 响应。"""

    def _post(self, payload):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.sid:
            headers["mcp-session-id"] = self.sid
        req = urllib.request.Request(self.url,
            data=json.dumps(payload).encode("utf-8"), headers=headers)
        raw = urllib.request.urlopen(req, timeout=self.timeout).read().decode("utf-8", "ignore")
        want = payload.get("id")
        for fm in re.finditer(r"^data:\s*(.*)$", raw, re.M):
            s = fm.group(1).strip()
            if not s.startswith("{"):
                continue
            try:
                d = json.loads(s)
            except json.JSONDecodeError:
                continue
            if want is None or d.get("id") == want:
                return d
        return None


log = dex.log

RANK_URL = "https://compass.jinritemai.com/shop/chance/rank-product"
DEFAULT_LOGIN_URL = dex.DEFAULT_LOGIN_URL


def find_compass_pages(sess):
    """列出当前所有罗盘域名页面 id。"""
    try:
        text = sess.call("tabs", {"action": "list"})
    except RuntimeError:
        return []
    ids = []
    for line in text.split("\n"):
        m = re.match(r"\[(\d+)\]\s+(\S*compass\.jinritemai\.com\S*)", line.strip())
        if m:
            pid = int(m.group(1))
            if pid not in ids:
                ids.append(pid)
    return ids


def close_page(sess, pid):
    if pid is None:
        return
    try:
        sess.call("tabs", {"action": "close", "page": pid})
        log(f"已关闭页面 {pid}")
    except RuntimeError as e:
        log(f"关闭页面 {pid} 失败（忽略）: {str(e)[:80]}")


def js_eval(sess, page, func):
    """在页面执行 JS 函数，返回其 JSON 字符串结果（剥掉 untrusted 标记）。

    evaluate 返回形如：
      [UNTRUSTED_PAGE_CONTENT nonce=... origin=...] ...提示文字...
      {json}
      [END_UNTRUSTED_PAGE_CONTENT nonce=...]
    这里剥掉两行标记与提示，返回纯 JSON 文本。
    """
    out = sess.call("evaluate", {"page": page, "func": func})
    # 去掉 [UNTRUSTED...] 开头的提示行（到第一个换行前）
    lines = out.split("\n")
    cleaned = []
    for line in lines:
        if line.startswith("[UNTRUSTED_PAGE_CONTENT") or line.startswith("[END_UNTRUSTED"):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned).strip()
    # 若仍有 untrusted 提示单行包裹，去掉非 JSON 前缀
    m = re.search(r"[{\[].*[}\]]", text, re.S)
    return m.group(0) if m else text


def get_tab_ref(sess, page, tab_text, timeout=30):
    """轮询快照，返回榜单 tab（如「短视频榜」）的 ref。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = sess.call("snapshot", {"page": page, "mode": "interactive", "depth": 24})
        for line in snap.split("\n"):
            if re.search(rf'tab "{re.escape(tab_text)}"', line) and "[ref=" in line:
                m = re.search(r"\[ref=(e\d+)\]", line)
                if m:
                    return m.group(1)
        time.sleep(2)
    raise RuntimeError(f"等待榜单 tab「{tab_text}」超时")


def click_tab(sess, page, tab_text):
    ref = get_tab_ref(sess, page, tab_text)
    log(f"点击榜单 tab「{tab_text}」ref={ref}")
    sess.call("act", {"page": page, "kind": "click", "ref": ref, "diff": "none"})
    time.sleep(3)


def is_tab_selected(sess, page, tab_text):
    """判断榜单 tab 是否选中：检查该 tab 祖先链上是否出现 -active 类名。"""
    func = (r'''() => {
      const els = [...document.querySelectorAll("span,div,li")];
      const el = els.find(e => (e.textContent || "").trim() === "%s" && e.children.length === 0);
      if (!el) return JSON.stringify({found: false});
      let cur = el;
      while (cur) {
        if (/active|selected|checked|cur/i.test(typeof cur.className === "string" ? cur.className : "")) {
          return JSON.stringify({found: true, active: true});
        }
        cur = cur.parentElement;
      }
      return JSON.stringify({found: true, active: false});
    }''' % tab_text)
    out = js_eval(sess, page, func)
    try:
        return json.loads(out).get("active", False)
    except Exception:
        return False


def click_brand_tag(sess, page, brand_text):
    """点击品牌 tag（如「非知名品牌」）。tagItem 是自定义组件，用 DOM 原生 click。"""
    func = (r'''() => {
      const els = [...document.querySelectorAll("div.tagItem-Kca1ie, div.tagItem, span, div")];
      const el = els.find(e => (e.textContent || "").trim() === "%s" && e.children.length === 0);
      if (!el) return JSON.stringify({ok: false, reason: "not found"});
      el.click();
      return JSON.stringify({ok: true});
    }''' % brand_text)
    out = js_eval(sess, page, func)
    log(f"点击品牌「{brand_text}」: {out[:120]}")
    time.sleep(3)


def read_state(sess, page):
    """读取当前筛选状态：榜单 tab、类目、品牌。

    - 榜单 tab 选中态：祖先链上出现 -active 类名（aurora-tabs-tab-active）
    - 品牌 tag 选中态：叶子节点自身 class 含 activeItem（tagItem-xxx activeItem-xxx）
    """
    func = r'''() => {
      const findLeaf = (kw) => {
        const els = [...document.querySelectorAll("span,div,li,a")];
        return els.find(e => (e.textContent || "").trim() === kw && e.children.length === 0);
      };
      const tabActive = (kw) => {
        const el = findLeaf(kw);
        if (!el) return null;
        let cur = el, active = false;
        while (cur) {
          if (/active|selected|checked|cur/i.test(typeof cur.className === "string" ? cur.className : "")) {
            active = true; break;
          }
          cur = cur.parentElement;
        }
        return {text: kw, active: active};
      };
      const tagActive = (kw) => {
        const el = findLeaf(kw);
        if (!el) return null;
        const cls = typeof el.className === "string" ? el.className : "";
        return {text: kw, active: /activeItem|active|selected|checked/i.test(cls)};
      };
      return JSON.stringify({
        shortVideoTab: tabActive("短视频榜"),
        brandWellKnown: tagActive("知名品牌"),
        brandUnknown: tagActive("非知名品牌"),
        category: (document.body.textContent || "").includes("母婴宠物 / 宠物生活") ? "母婴宠物/宠物生活" : "未确认"
      });
    }'''
    out = js_eval(sess, page, func)
    try:
        return json.loads(out)
    except Exception:
        return {"raw": out}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="自动进入抖店电商罗盘短视频榜单目标页")
    ap.add_argument("--keep-open", action="store_true",
                    help="运行结束后保留浏览器页面（调试/人工核对用，默认自动关闭）")
    ap.add_argument("--skip-login", action="store_true",
                    help="跳过登录入口（浏览器已登录时更快）")
    args = ap.parse_args()

    sess = RobustSession().connect()
    try:
        sess.call("name_session", {"name": "compass-video-rank"})
    except RuntimeError:
        pass

    pid = None
    try:
        # 1. 登录抖店后台（复用已验证的登录入口 + 登录态探测）
        if not args.skip_login:
            dex.visit_login_entry(sess, DEFAULT_LOGIN_URL)
        dex.ensure_login(sess, DEFAULT_LOGIN_URL)

        # 2. 直达罗盘短视频榜单页
        log(f"直达榜单页: {RANK_URL}")
        out = sess.call("tabs", {"action": "new", "url": RANK_URL})
        m = re.search(r"page\s+(\d+)", out)
        if not m:
            raise RuntimeError(f"打开榜单页失败: {out[:200]}")
        pid = int(m.group(1))
        time.sleep(8)
        log(f"榜单页 page id = {pid}")

        # 3. 选「短视频榜」tab
        if not is_tab_selected(sess, pid, "短视频榜"):
            click_tab(sess, pid, "短视频榜")

        # 4. 选「非知名品牌」，并确保「知名品牌」未被选中（只留非知名）
        st = read_state(sess, pid)
        if st.get("brandUnknown") and not st["brandUnknown"].get("active"):
            click_brand_tag(sess, pid, "非知名品牌")
            time.sleep(2)
        st = read_state(sess, pid)
        if st.get("brandWellKnown") and st["brandWellKnown"].get("active"):
            click_brand_tag(sess, pid, "知名品牌")  # 若互斥多选，点掉知名品牌
            time.sleep(2)

        # 5. 汇总状态
        st = read_state(sess, pid)
        log(f"最终状态: {json.dumps(st, ensure_ascii=False)}")
        if st.get("shortVideoTab", {}).get("active") and \
           st.get("brandUnknown", {}).get("active"):
            log("✓ 已到达目标：短视频榜 / 非知名品牌 / 母婴宠物·宠物生活")
        else:
            log("⚠ 部分条件未确认选中，请人工核对")

        print(f"RESULT_PAGE={pid}")
        print(f"RESULT_URL={RANK_URL}")
    finally:
        # 关闭本次新开的罗盘页面（保留用户原有页面）
        if pid is not None and not args.keep_open:
            close_page(sess, pid)


if __name__ == "__main__":
    main()
