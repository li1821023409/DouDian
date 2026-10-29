#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确保晓风运营插件已安装且在当前页面生效，未生效时自动修复。

为什么需要：插件是「加载未打包扩展」，BrowserOS 每次重启后经常不自动加载。
表现为页面正常显示商品列表，但 `<td p[itemid]>` 属性不存在，
于是 fetch_rank.py 抓到 0 个商品，整条流水线白跑。

【根治】跑一次 `scripts\\install_extension.py` 把启动参数固化进快捷方式，
        以后浏览器每次打开就自动带插件，本脚本的修复分支基本用不上了。
        本脚本只用一条只读接口判断插件在不在（CDP 9110 的 /json/list 能列出
        扩展的 service_worker），在就直接通过，不会重复挂载。

检测与处理分三种情况：
  1. 插件源目录缺失        → 报错，提示从 git 恢复（真的没装）
  2. 源在但页面无注入      → 调 fix_extension.ps1 重新挂载 + 刷新页面（被拦截）
  3. 已生效                → 直接通过

用法（建议放在 run_pipeline 的"打开页面"之后、"抓取"之前）：
    D:\\Install\\Python\\python.exe scripts\\ensure_extension.py
退出码：0 正常 / 2 插件源缺失 / 3 服务未启动 / 4 无榜单页 / 5 加载失败 / 6 注入失败
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
PLUGIN_DIR = PROJ / "插件" / "晓风运营插件-30.3.3"
FIX_PS1 = HERE / "fix_extension.ps1"
EXT_ID = "oiinpblopagmgmihimfcfjpcdfimegme"
CDP = "http://127.0.0.1:9110"
RELOAD_WAIT = 8

PROBE_JS = ("() => JSON.stringify({"
            "rows: document.querySelectorAll('tbody tr').length,"
            "items: document.querySelectorAll('tbody td p[itemid]').length,"
            "tab: (document.querySelector(\"[class*='tabs-tab-active']\")||{}).innerText||''"
            "})")


def _open_no_proxy(url, timeout=6):
    """本地地址一律绕过系统代理——这台机器的环境代理会把 127.0.0.1 打成 502。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as r:
        return r.read()


def check_cdp():
    try:
        d = json.loads(_open_no_proxy(CDP + "/json/version"))
        return d.get("Browser", "?")
    except Exception:
        return None


def ext_loaded():
    """扩展是否已经在浏览器里跑起来了 —— 读 CDP 的目标列表，纯只读。

    chrome-extension://<id> 的 service_worker 出现即视为已加载。
    启动参数 --load-extension 加载的、以及 loadUnpacked 挂上的，这里都能看到。
    """
    try:
        d = json.loads(_open_no_proxy(CDP + "/json/list", timeout=6))
    except Exception:
        return None                      # 查不到（CDP 没开）→ 交给调用方决定
    for t in d:
        url = (t.get("url") or "")
        if url.startswith(f"chrome-extension://{EXT_ID}/"):
            return True
    return False


def load_cvr():
    spec = importlib.util.spec_from_file_location(
        "cvr", HERE / "compass_video_rank.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def find_rank_pages(sess):
    text = sess.call("tabs", {"action": "list"})
    out = []
    for line in text.split("\n"):
        m = re.match(r"\[(\d+)\]\s+(\S*compass\.jinritemai\.com\S*)", line.strip())
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


def probe(sess, pid):
    out = sess.call("evaluate", {"page": pid, "func": PROBE_JS})
    for line in out.split("\n"):
        s = line.strip()
        if s.startswith("{") and "items" in s:
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass
    return {"rows": 0, "items": 0, "tab": ""}


def reload_page(sess, pid):
    sess.call("evaluate", {"page": pid,
                           "func": "() => { location.reload(); return 1; }"})
    time.sleep(RELOAD_WAIT)


def run_fix():
    """调现有的 PowerShell 脚本重新挂载扩展（需要 CDP 9110）。"""
    print("  重新加载扩展 ...")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(FIX_PS1)],
            capture_output=True, text=True, errors="ignore", timeout=90)
    except FileNotFoundError:
        print("  ✗ 找不到 powershell，无法自动加载扩展")
        return False
    except subprocess.TimeoutExpired:
        print("  ✗ 加载扩展超时")
        return False
    ok = EXT_ID in (r.stdout or "")
    for line in (r.stdout or "").splitlines():
        if line.strip():
            print("    " + line.strip()[:100])
    return ok


def main():
    ap = argparse.ArgumentParser(description="确保晓风插件已加载并注入")
    ap.add_argument("--load", action="store_true",
                    help="只确保扩展已加载，不碰页面（不刷新，不会重置榜单 tab）")
    ap.add_argument("--check", action="store_true",
                    help="只检查页面是否注入，不尝试修复")
    args = ap.parse_args()

    print("=== 晓风插件检查 ===")

    # 1. 插件源是否在（判断"装没装"）
    manifest = PLUGIN_DIR / "manifest.json"
    if not manifest.exists():
        print(f"✗ 插件源缺失：{manifest}")
        print("  这台机器上没有插件源文件，需要从仓库恢复：")
        print("    git checkout -- 插件/")
        print("  然后重跑本脚本。")
        return 2
    print(f"✓ 插件源存在：{PLUGIN_DIR.name}")

    # 2. 依赖服务
    browser = check_cdp()
    if not browser:
        print(f"✗ CDP {CDP} 不可达 —— BrowserOS neo 没启动")
        print("  先启动 BrowserOS neo，再重试。")
        return 3
    print(f"✓ CDP 可用：{browser}")

    # ---- --load：只加载扩展，不碰页面 ----
    # 用于流水线第一步：扩展加载好之后，compass_video_rank 新开的页面会自动注入，
    # 不需要刷新，也就不会把「短视频榜」重置回「总榜」。
    if args.load:
        alive = ext_loaded()
        if alive:
            print("✓ 扩展已在运行（无需重复挂载）")
            print("  后续新开的页面会自动注入，跳过修复步骤")
            return 0
        if alive is None:
            print("! 读不到 CDP 目标列表，按未加载处理")
        if not run_fix():
            print("✗ 扩展加载失败")
            print("  根治办法：跑一次 python scripts\\install_extension.py，"
                  "把 --load-extension 固化进快捷方式")
            return 5
        print("✓ 扩展已加载（后续新开的页面会自动注入）")
        return 0

    try:
        cvr = load_cvr()
        sess = cvr.RobustSession().connect()
    except Exception as e:
        print(f"✗ 连接 browseros MCP 失败：{type(e).__name__}: {str(e)[:100]}")
        print("  确认 9010 端口有服务（browseros-claw-server 是否在运行）。")
        return 3

    # 3. 找榜单页并检测注入
    pages = find_rank_pages(sess)
    if not pages:
        print("✗ 当前没有罗盘榜单页面")
        print("  先打开：python scripts\\compass_video_rank.py")
        return 4

    pid, url = pages[-1]
    st = probe(sess, pid)
    print(f"  页面 [{pid}] {url[:60]}")
    print(f"  表格 {st['rows']} 行，插件属性 {st['items']} 个，当前 tab：{st.get('tab') or '未知'}")

    if st["items"] > 0:
        print("✓ 插件已生效，无需处理")
        return 0

    # ---- --check：只报告，不修复 ----
    if args.check:
        print("✗ 插件未注入")
        print("  注意：不要在这里刷新页面——刷新会把榜单 tab 重置回「总榜」，")
        print("        导致抓取到 0 个视频。正确做法是重跑「打开页面」步骤，新开一个页面。")
        return 6

    # 4. 默认模式（人工排查用）：源在但没注入 → 重新挂载 + 刷新
    print("! 插件源存在但页面未注入，判定为「重启后被拦截」，开始修复")
    print("  提示：本模式会刷新页面，刷新后榜单 tab 会回到「总榜」，")
    print("        之后需要重跑 compass_video_rank.py 重新切到「短视频榜」。")
    if not run_fix():
        print("✗ 扩展重新加载失败")
        print("  人工处理：chrome://extensions → 开启开发者模式 → 加载未打包的扩展程序")
        print(f"            选择 {PLUGIN_DIR}")
        return 5

    reload_page(sess, pid)
    st = probe(sess, pid)
    print(f"  刷新后：表格 {st['rows']} 行，插件属性 {st['items']} 个，tab：{st.get('tab') or '未知'}")
    if st["items"] > 0:
        print("✓ 修复成功，插件已生效")
        print("  提醒：页面 tab 可能已回到「总榜」，跑抓取前需重新执行 compass_video_rank.py。")
        return 0

    print("✗ 重新加载并刷新后仍未注入")
    print("  可能原因：插件版本与当前浏览器不兼容，或 manifest 被改坏")
    print("  人工检查：chrome://extensions 里「晓风运营插件」是否为「已启用」")
    return 6


if __name__ == "__main__":
    sys.exit(main())
