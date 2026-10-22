#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动整理抖店数据 —— 商品导出核心脚本

用途：驱动 browseros-neo MCP 浏览器会话，走通抖店「商品-商品管理-售卖中」
      的异步导出流程，并把下载到的 xlsx 搬运到指定目录。

设计要点：
- 抖店导出是【异步任务】：点击导出 -> 后台生成 -> 需从「查看导出记录」页下载。
  因此必须经历 提交 -> 轮询 -> 下载 三段。
- 页面 ref 每次导航后失效，故每一步都重新 snapshot 取 ref，绝不复用旧 ref。
- 一天导出多次时加 --with-slot，文件名带 _上午/_下午/_晚间，避免撞名互删；
  默认 --keep 2，配合每天两次（9:00 / 21:00）的定时任务刚好各留一份。
- 归档目录已于 2026-10-17 从「D:\\Data\\抖店素材」改名为「D:\\Data\\DouDian」。
  脚本内置重定向兜底：传入旧目录名会自动纠正到新目录并打印提示，
  因此旧会话里缓存的旧命令仍能正确工作。

用法：
    python doudian_export.py --target-dir "D:\\Data\\DouDian\\商品数据"
    python doudian_export.py --target-dir "D:\\..." --tab all
    python doudian_export.py --target-dir "D:\\..." --with-slot   # 文件名带时段
    python doudian_export.py --target-dir "D:\\..." --dry-run    # 只探测不落盘
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import urllib.error

MCP_URL = "http://127.0.0.1:9010/mcp"
TAB_LIST_URL = "https://fxg.jinritemai.com/ffa/g/list"

# 收藏夹里的抖店登录入口。默认用简版路径，实测带参数的完整书签 URL
# 只会停在官网空壳页（无可点击链接、不跳转后台），故用基础路径更可靠。
# 若你换了新的登录书签，用 --login-url 覆盖即可。
DEFAULT_LOGIN_URL = "https://fxg.jinritemai.com/login/common/channel"

TAB_MAP = {"onSale": "售卖中", "all": "全部", "offSale": "已下架"}

# 落到文件名里的状态后缀
FILE_LABEL = {"onSale": "销售中", "all": "全部", "offSale": "已下架"}

# ---- 目录改名兼容（2026-10-17）----
# 归档目录已从 D:\Data\抖店素材 改名为 D:\Data\DouDian。
# OpenClaw 的对话上下文在会话创建时就冻结了 SKILL.md 内容，
# 改文件不会热重载——旧会话仍会传旧路径，导致脚本在旧目录重建文件夹。
# 故在此做兜底重定向：任何指向旧目录的路径都自动纠正到新目录。
OLD_ROOT = "抖店素材"
NEW_ROOT = "DouDian"


def normalize_target_dir(path):
    """把遗留的旧目录路径重定向到改名后的新目录。"""
    if not path:
        return path
    parts = re.split(r"[\\/]+", os.path.normpath(path))
    if OLD_ROOT not in parts:
        return path
    new_parts = [NEW_ROOT if p == OLD_ROOT else p for p in parts]
    new_path = os.path.sep.join(new_parts)
    if os.path.normcase(new_path) != os.path.normcase(path):
        log(f"检测到旧目录名，已自动重定向:\n  {path}\n  → {new_path}")
    return new_path

# 会话是长连接；ref 只在同一次连接、且导航前有效。
class McpSession:
    def __init__(self, url=MCP_URL, timeout=90):
        self.url = url
        self.timeout = timeout
        self.sid = None
        self._id = 0

    def _post(self, payload):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.sid:
            headers["mcp-session-id"] = self.sid
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"), headers=headers
        )
        raw = urllib.request.urlopen(req, timeout=self.timeout).read().decode("utf-8", "ignore")
        # streamable-http 返回 SSE 帧，取第一段 data: {json}
        m = re.search(r"data:\s*(\{.*\})", raw, re.S)
        return json.loads(m.group(1)) if m else None

    def connect(self):
        # 首次请求的响应头里带 session id，需要单独抓
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        payload = {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "doudian-export", "version": "1"}},
        }
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            sid = r.headers.get("mcp-session-id")
            r.read()
        self.sid = sid
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def call(self, tool, args, retries=3):
        for attempt in range(1, retries + 1):
            self._id += 1
            try:
                resp = self._post({
                    "jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                    "params": {"name": tool, "arguments": args},
                })
            except (urllib.error.URLError, OSError) as e:
                if attempt == retries:
                    raise RuntimeError(f"MCP 连接失败: {e}")
                time.sleep(2 * attempt)
                self.connect()          # 断线重连并重取 session
                continue
            res = resp.get("result", {})
            text = res.get("content", [{}])[0].get("text", "")
            if res.get("isError"):
                raise RuntimeError(f"{tool} 返回错误: {text[:300]}")
            return text
        raise RuntimeError(f"{tool} 重试 {retries} 次仍失败")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_doudian_pages(sess):
    """列出当前所有抖店域名页面的 page id。"""
    try:
        text = sess.call("tabs", {"action": "list"})
    except RuntimeError:
        return []
    ids = []
    for line in text.split("\n"):
        m = re.match(r"\[(\d+)\]\s+(\S*fxg\.jinritemai\.com\S*)", line.strip())
        if m:
            pid = int(m.group(1))
            if pid not in ids:
                ids.append(pid)
    return ids


def close_page(sess, pid):
    """关闭指定页面，失败只记日志不影响主流程。"""
    if pid is None:
        return False
    try:
        sess.call("tabs", {"action": "close", "page": pid})
        log(f"已关闭页面 {pid}")
        return True
    except RuntimeError as e:
        log(f"关闭页面 {pid} 失败（忽略）: {str(e)[:80]}")
        return False


def visit_login_entry(sess, login_url, wait=6):
    """打开收藏夹里的抖店登录入口，唤醒会话，随后立即关闭。

    实测结论（2026-10-17）：
    - 带完整参数的收藏 URL 与简版路径，都只会停在官网空壳页，
      无可点击链接、也不跳后台；
    - 但访问一次能唤醒/刷新浏览器侧的登录态，所以保留这一步，
      真正的后台入口仍以商品管理页 URL 为准。

    访问完立刻关掉，避免浏览器里同时留下「抖店」和「商品管理」两个标签。
    """
    log(f"访问登录入口: {login_url}")
    out = sess.call("tabs", {"action": "new", "url": login_url})
    m = re.search(r"page\s+(\d+)", out)
    if not m:
        raise RuntimeError(f"打开登录入口失败: {out[:200]}")
    pid = int(m.group(1))
    log(f"登录入口 page id = {pid}，停留 {wait}s 唤醒会话")
    time.sleep(wait)
    close_page(sess, pid)
    return pid


def ensure_login(sess, login_url, timeout=30):
    """确认登录态。若未登录则给出明确提示，而不是让脚本在页面上瞎等。"""
    probe = sess.call("tabs", {"action": "new", "url": f"{TAB_LIST_URL}?tab=onSale"})
    m = re.search(r"page\s+(\d+)", probe)
    if not m:
        raise RuntimeError(f"登录态探测失败: {probe[:200]}")
    pid = int(m.group(1))
    log(f"登录探测页 page id = {pid}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        try:
            snap = sess.call("snapshot", {"page": pid, "mode": "interactive", "depth": 12})
        except RuntimeError:
            continue
        if "导出查询商品" in snap or "商品管理" in snap:
            log("登录态正常，已进入商品管理页")
            return pid
        if re.search(r"登录|扫码|手机号验证|验证码登录", snap):
            close_page(sess, pid)
            raise RuntimeError(
                f"抖店登录态已失效。请先在浏览器中用收藏夹入口"
                f"（{login_url}）登录抖店，然后重新执行本工作流。"
            )
    return pid


def open_page(sess, want_tab, login_url=DEFAULT_LOGIN_URL, skip_login=False):
    """走登录入口后，开一个属于当前连接的抖店商品列表页。

    browseros 的会话归属规则：只有「本次连接自己开的页面」才带 attached session，
    跨连接复用旧 tab 会在 snapshot 时报 "has no attached session"。
    因此这里总是新开，而不是去 list 里捡现成的。
    """
    try:
        sess.call("name_session", {"name": "doudian-export"})
    except RuntimeError:
        pass

    if not skip_login:
        visit_login_entry(sess, login_url)

    pid = ensure_login(sess, login_url)
    url = f"{TAB_LIST_URL}?tab={want_tab}"
    log(f"打开商品管理页: {url}")
    sess.call("navigate", {"page": pid, "action": "url", "url": url})
    time.sleep(4)
    log(f"商品管理页 page id = {pid}")
    return pid


def get_ref(sess, page, text_pattern, timeout=20):
    """轮询快照直到出现匹配文本，返回其 ref。抖店渲染较慢，需要重试。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = sess.call("snapshot", {"page": page, "mode": "interactive", "depth": 12})
        for line in snap.split("\n"):
            if re.search(text_pattern, line):
                m = re.search(r"\[ref=(e\d+)\]", line)
                if m:
                    return m.group(1)
        time.sleep(2)
    raise RuntimeError(f"等待元素超时，未匹配到: {text_pattern}")


def select_tab(sess, page, tab_key):
    """确保停在目标 tab（售卖中/全部）。抖店 tab 用 query 参数控制，最稳。"""
    label = TAB_MAP.get(tab_key, tab_key)
    log(f"切换到「{label}」标签")
    sess.call("navigate", {"page": page, "action": "url",
                           "url": f"{TAB_LIST_URL}?tab={tab_key}"})
    time.sleep(3)


def submit_export(sess, page, dry_run=False):
    log("点击「导出查询商品」")
    ref = get_ref(sess, page, r'button "导出查询商品"')
    sess.call("act", {"page": page, "kind": "click", "ref": ref, "diff": "none"})

    log("等待导出确认弹窗（含报表字段数量）")
    time.sleep(2)
    snap = sess.call("snapshot", {"page": page, "mode": "interactive", "depth": 14})
    m = re.search(r"当前导出(\d+)个商品", snap.replace("\n", " "))
    count = m.group(1) if m else "未知"
    fields = re.search(r"报表字段（共(\d+)个）", snap.replace("\n", " "))
    nfield = fields.group(1) if fields else "?"
    log(f"弹窗确认：{count} 个商品 / {nfield} 个报表字段")

    if dry_run:
        log("[dry-run] 到此为止，不提交导出")
        return count

    # 弹窗里「导出」是真正的提交按钮，注意与页面上的「导出查询商品」区分
    ok_ref = get_ref(sess, page, r'button "导出"')
    sess.call("act", {"page": page, "kind": "click", "ref": ok_ref, "diff": "none"})
    log("导出任务已提交，等待后台生成")
    return count


def close_export_dialog(sess, page):
    """关闭导出确认弹窗。

    点击「导出」提交后弹窗不会立刻消失，它的遮罩层会挡住
    下方「查看导出记录」按钮，导致 act 报 "is covered by ..."。
    弹窗里同时存在 Close 和 取消 两个可点元素，这里按 Close -> 取消 顺序尝试，
    任一成功即返回；失败则重试两轮，确保遮罩被撤掉。
    """
    for attempt in range(1, 3):
        try:
            snap = sess.call("snapshot", {"page": page,
                                          "mode": "interactive", "depth": 14})
        except RuntimeError:
            return False
        # 快照里 cell 行排在 link/button 行之前，必须取带 ref 的那一行
        for pattern in (r'button "Close"', r'button "取消"', r'button "关闭"'):
            for line in snap.split("\n"):
                if re.search(pattern, line) and "[ref=" in line:
                    m = re.search(r"\[ref=(e\d+)\]", line)
                    if not m:
                        continue
                    try:
                        log(f"关闭导出弹窗（{pattern}），第 {attempt} 轮")
                        sess.call("act", {"page": page, "kind": "click",
                                          "ref": m.group(1), "diff": "none"})
                        time.sleep(2)
                        return True
                    except RuntimeError:
                        continue
        time.sleep(1)
    log("警告：未能确认导出弹窗已关闭，继续尝试点击查看导出记录")
    return False


def click_with_retry(sess, page, ref, attempts=3, close_dialog_on_fail=True):
    """点击元素，遇「被遮挡」时先关弹窗再重试。

    抖店是 SPA，弹窗遮罩消失有延迟，首次点击容易撞上
    "is covered by ecom-g-drawer..."，这里统一兜住这种瞬时状态。
    """
    last = ""
    for i in range(1, attempts + 1):
        try:
            sess.call("act", {"page": page, "kind": "click", "ref": ref, "diff": "none"})
            return True
        except RuntimeError as e:
            last = str(e)
            if "covered by" not in last.lower() or i == attempts:
                break
            log(f"点击被遮挡，第 {i}/{attempts} 轮：尝试关闭弹窗后重试")
            if close_dialog_on_fail:
                close_export_dialog(sess, page)
            time.sleep(2)
    raise RuntimeError(f"点击失败: {last[:220]}")


def wait_and_download(sess, page, target_dir, tab_key="onSale", timeout=180,
                       with_slot=False):
    log("打开「查看导出记录」")
    close_export_dialog(sess, page)
    # 记录当前已有的抖店页面，便于事后识别「查看导出记录」新开的标签
    before = find_doudian_pages(sess)
    ref = get_ref(sess, page, r'"查看导出记录"')
    click_with_retry(sess, page, ref)
    time.sleep(2)

    # 抖店点「查看导出记录」会新开一个标签页，需要切到该页操作下载
    excel_page = page
    after = find_doudian_pages(sess)
    new_pages = [p for p in after if p not in before]
    if new_pages:
        excel_page = new_pages[0]
        log(f"「查看导出记录」在新标签打开，切换到 page id = {excel_page}")
        time.sleep(3)

    log("轮询等待「下载报表」出现")
    deadline = time.time() + timeout
    dl_ref = None
    while time.time() < deadline:
        try:
            snap = sess.call("snapshot", {"page": excel_page,
                                          "mode": "interactive", "depth": 30})
            # 必须取【同时含 text 和 [ref=]】的行：表格快照里
            # `cell "下载报表"` 出现在 `link "下载报表" [ref=eN]` 之前，
            # 只按文字匹配会拿到没有 ref 的 cell 行。
            for line in snap.split("\n"):
                if '"下载报表"' in line and "[ref=" in line:
                    m = re.search(r"\[ref=(e\d+)\]", line)
                    if m:
                        dl_ref = m.group(1)
                        break
            if dl_ref:
                break
        except RuntimeError:
            pass
        time.sleep(5)
    if not dl_ref:
        raise RuntimeError(f"等待下载链接超时（{timeout}s），导出可能失败或超量")

    log(f"触发下载（ref={dl_ref}）")
    res = trigger_download(sess, excel_page, dl_ref)

    m = re.search(r'to:\s*(.+?)\s*$', res.strip(), re.M)
    if not m:
        raise RuntimeError(f"未能解析下载路径: {res[:200]}")
    src = m.group(1).strip().strip('"')
    size = re.search(r"\((\d+) bytes\)", res)
    log(f"下载完成: {os.path.basename(src)} ({size.group(1) if size else '?'} bytes)")

    if os.path.normcase(os.path.dirname(src)) == os.path.normcase(target_dir):
        log("文件已在目标目录，按规则重命名")
        return move_to_target(src, target_dir + os.sep + os.path.basename(src),
                              tab_key=tab_key, with_slot=with_slot)
    return move_to_target(src, target_dir, tab_key=tab_key, with_slot=with_slot)


def trigger_download(sess, page, ref, attempts=3):
    """触发下载并返回落盘路径。

    前提：浏览器必须关闭「下载前询问保存位置」，否则会弹出原生保存对话框，
    browseros 等不到文件落地而抛 "Download timed out after 60000ms"。
    抖店的临时下载链接有有效期，首次超时后需要重新取 ref 再试。
    """
    last = ""
    for i in range(1, attempts + 1):
        try:
            return sess.call("download", {"page": page, "ref": ref}, retries=1)
        except RuntimeError as e:
            last = str(e)
            log(f"下载尝试 {i}/{attempts} 失败: {last[:120]}")
            if i < attempts:
                # 链接可能已失效，重新快照取一个最新 ref
                time.sleep(3)
                try:
                    snap = sess.call("snapshot", {"page": page,
                                                  "mode": "interactive", "depth": 30})
                    for line in snap.split("\n"):
                        if '"下载报表"' in line and "[ref=" in line:
                            m = re.search(r"\[ref=(e\d+)\]", line)
                            if m:
                                ref = m.group(1)
                                log(f"改用新的下载 ref={ref}")
                                break
                except RuntimeError:
                    pass
    raise RuntimeError(
        f"下载连续 {attempts} 次失败：{last[:200]}。"
        "若提示保存位置对话框，请到浏览器设置中关闭「下载前询问每个文件的保存位置」。"
    )


def build_filename(tab_key, with_slot=False, stamp=None):
    """生成目标文件名：年月日 + 商品状态[ + 时段]，例如 20261017销售中_晚间.xlsx。

    抖店原始文件名是 productExport-<uuid>.xlsx，重复下载还会加 (1)(2) 后缀，
    完全无法排序。这里统一改成 <YYYYMMDD><状态>[_<时段>].xlsx。

    with_slot=True 时按时段区分（如 _上午 / _晚间），用于一天导出多次的场景：
    否则同一天早、晚两次导出会撞名，晚的那次会把早的覆盖或顶掉。
    """
    stamp = stamp or time.strftime("%Y%m%d")
    label = FILE_LABEL.get(tab_key, tab_key)
    slot = f"_{time_slot()}" if with_slot else ""
    return f"{stamp}{label}{slot}.xlsx"


def time_slot(hour=None):
    """按小时归入时段标签。"""
    hour = time.localtime().tm_hour if hour is None else hour
    if hour < 12:
        return "上午"
    if hour < 18:
        return "下午"
    return "晚间"


def move_to_target(src, target_dir, tab_key="onSale", with_slot=False):
    """把下载文件搬到目标目录并按「年月日+状态[+时段]」重命名。"""
    os.makedirs(target_dir, exist_ok=True)
    ext = os.path.splitext(src)[1] or ".xlsx"
    name = build_filename(tab_key, with_slot=with_slot)
    dst = os.path.join(target_dir, name.replace(".xlsx", ext))
    # 同名已存在（同一天同一时段重复运行）时补精确时间戳，避免静默覆盖
    if os.path.exists(dst):
        stem = os.path.splitext(dst)[0]
        dst = f"{stem}_{time.strftime('%H%M%S')}{ext}"
    shutil.move(src, dst)
    log(f"已归档到: {dst}")
    return dst


def clean_old_files(target_dir, keep=1, pattern="*.xlsx"):
    """清理目标目录里的旧导出文件，只保留最新的 keep 份。

    安全约束：
    - 只匹配导出产生的 .xlsx（可传 --keep-pattern 自定义），不碰其他文件。
    - 默认保留最新 1 份，--keep 0 表示全清。
    - 逐个删除，每步打印文件名，便于事后追溯。
    """
    if not os.path.isdir(target_dir):
        return []
    files = [os.path.join(target_dir, f) for f in os.listdir(target_dir)
             if fnmatch.fnmatch(f.lower(), pattern.lower())]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    victims = files[keep:]
    for p in victims:
        try:
            os.remove(p)
            log(f"已删除旧文件: {os.path.basename(p)}")
        except OSError as e:
            log(f"删除失败 {os.path.basename(p)}: {e}")
    if not victims:
        log(f"无需清理，当前 {len(files)} 个文件，已保留最新 {keep} 份")
    return victims


def main():
    ap = argparse.ArgumentParser(description="自动整理抖店数据 —— 商品导出")
    ap.add_argument("--target-dir", required=True, help="导出文件保存目录")
    ap.add_argument("--tab", default="onSale", choices=list(TAB_MAP), help="商品状态 tab")
    ap.add_argument("--timeout", type=int, default=180, help="等待导出生成的秒数")
    ap.add_argument("--dry-run", action="store_true", help="只走到弹窗，不真正导出")
    ap.add_argument("--keep", type=int, default=2,
                    help="目标目录保留最新几份导出文件，默认 2；0 表示全部删除")
    ap.add_argument("--no-clean", action="store_true", help="本次不清理旧文件")
    ap.add_argument("--keep-pattern", default="*.xlsx", help="清理时匹配的文件名模式")
    ap.add_argument("--with-slot", action="store_true",
                    help="文件名追加时段后缀（_上午/_下午/_晚间），"
                         "一天导出多次时使用，避免早晚上两次撞名")
    ap.add_argument("--login-url", default=DEFAULT_LOGIN_URL,
                    help="收藏夹里的抖店登录入口 URL")
    ap.add_argument("--skip-login", action="store_true",
                    help="跳过登录入口，直接进商品管理页（浏览器已登录时更快）")
    ap.add_argument("--keep-open", action="store_true",
                    help="运行结束后保留浏览器页面（调试用，默认自动关闭）")
    ap.add_argument("--keep-n", type=int, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()
    # --keep-n 作为 --keep 的别名，兼容习惯写法
    if args.keep_n is not None:
        args.keep = args.keep_n

    # 目录改名兜底：纠正调用方传入的旧路径（旧会话会传旧目录名）
    args.target_dir = normalize_target_dir(args.target_dir)

    log(f"连接 browseros-neo MCP: {MCP_URL}")
    sess = McpSession().connect()
    pages_before = set(find_doudian_pages(sess))
    page = None
    try:
        page = open_page(sess, args.tab, login_url=args.login_url,
                         skip_login=args.skip_login)

        # open_page 内已导航到目标 tab，无需再调 select_tab
        count = submit_export(sess, page, dry_run=args.dry_run)

        if args.dry_run:
            log("dry-run 结束，未产生任何文件")
            return 0

        dst = wait_and_download(sess, page, args.target_dir, tab_key=args.tab,
                                timeout=args.timeout, with_slot=args.with_slot)
        log(f"完成，本次导出商品数 {count}，文件 {dst}")

        if not args.no_clean:
            log(f"开始清理旧文件（保留最新 {args.keep} 份）")
            clean_old_files(args.target_dir, keep=args.keep,
                            pattern=args.keep_pattern)

        print(f"\nRESULT_PATH={dst}")
        return 0
    finally:
        # 无论成功失败都关掉本次打开的所有抖店页面（含新开的导出记录页），
        # 避免浏览器里堆积标签页。
        if not args.keep_open:
            try:
                leftover = [p for p in find_doudian_pages(sess)
                            if p not in pages_before]
            except Exception:
                leftover = [page] if page is not None else []
            if leftover:
                log(f"收尾：关闭本次打开的页面 {leftover}")
                for pid in leftover:
                    close_page(sess, pid)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"\n[失败] {e}", file=sys.stderr)
        sys.exit(1)
