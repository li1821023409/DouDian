#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「晓风运营插件」永久挂到 BrowserOS neo 的启动参数上（装一次，以后每次自动加载）

为什么要这么做
--------------
插件是**未打包扩展**（unpacked）。Chrome 对这类扩展有两种加载方式：

1. `CDP Extensions.loadUnpacked`（fix_extension.ps1 现在用的）
   → **只在本次会话有效**。实测加载后 `Secure Preferences` 里根本不会新增条目，
     浏览器一重启就没了 —— 这就是「总是打开失败」的根因。
2. 启动参数 `--load-extension=<插件目录>`
   → 每次启动都会加载，扩展 ID 仍是按目录路径算出来的那个，换会话也不会丢。

本脚本把第 2 种固化到快捷方式里：在目标 chrome.exe 后面补一个
`--load-extension="D:\\Data\\DouDian\\插件\\晓风运营插件-30.3.3"`。

为什么不改 Chrome 配置
--------------------
「安装一次就永久生效」需要往 profile 的 `Secure Preferences` 里写扩展条目，
但 Chrome 对这份文件做了 HMAC 校验（`protection.macs`），手改会整份被丢弃；
把插件重新打包成 crx 又会换掉扩展 ID（现在的 ID 是按目录路径算的），
插件里已登录的状态会丢。改启动参数既保住 ID，又不用碰受保护配置。

用法
----
    python scripts/install_extension.py            # 打补丁（自动备份 .lnk.bak）
    python scripts/install_extension.py --check    # 只看现在挂没挂
    python scripts/install_extension.py --restore  # 从 .lnk.bak 还原

注意：改完要**完全退出 BrowserOS neo 再重新打开**才生效；
      当前这次会话可以用 `ensure_extension.py --load` 先顶上。
"""
import argparse
import shutil
import struct
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
PLUGIN_DIR = PROJ / "插件" / "晓风运营插件-30.3.3"
ARG_FLAG = "--load-extension="

LNK_SIG = b"BrowserClaw"
HEADER = 0x4C
F_IDLIST, F_LINKINFO, F_NAME, F_RELPATH, F_WORKDIR, F_ARGS, F_ICON, F_UNICODE = (
    0x1, 0x2, 0x4, 0x8, 0x10, 0x20, 0x40, 0x80)


def shortcut_dirs():
    home = Path.home()
    return [
        home / "Desktop",
        home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        home / "AppData" / "Roaming" / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar",
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"),
    ]


def find_shortcuts():
    out = []
    for d in shortcut_dirs():
        if not d.is_dir():
            continue
        for p in d.rglob("*.lnk"):
            try:
                if LNK_SIG in p.read_bytes():
                    out.append(p)
            except OSError:
                pass
    return out


def _strings(data: bytes, flags: int, off: int):
    """按 LinkFlags 顺序读出 StringData，返回 [(flag, 值, 该段的起止偏移)]。"""
    out = []
    uni = bool(flags & F_UNICODE)
    for bit, _ in ((F_NAME, "name"), (F_RELPATH, "rel"), (F_WORKDIR, "work"),
                   (F_ARGS, "args"), (F_ICON, "icon")):
        if not flags & bit:
            continue
        cnt = struct.unpack_from("<H", data, off)[0]
        start = off
        off += 2
        nbytes = cnt * 2 if uni else cnt
        raw = data[off:off + nbytes]
        off += nbytes
        val = raw.decode("utf-16-le" if uni else "mbcs", "ignore")
        out.append((bit, val, start, off))
    return out, off


def parse(path: Path):
    data = path.read_bytes()
    hsize, _clsid, flags = struct.unpack_from("<I16sI", data, 0)
    off = hsize
    if flags & F_IDLIST:
        off += 2 + struct.unpack_from("<H", data, off)[0]
    if flags & F_LINKINFO:
        off += struct.unpack_from("<I", data, off)[0]
    items, end = _strings(data, flags, off)
    return data, flags, hsize, items, end


def current_args(path: Path) -> str:
    _d, _f, _h, items, _e = parse(path)
    for bit, val, _s, _o in items:
        if bit == F_ARGS:
            return val
    return ""


def _backup(path: Path) -> Path:
    bak = path.with_suffix(".lnk.bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def patch(path: Path, arg: str) -> str:
    """在 StringData 里插入/替换 COMMAND_LINE_ARGUMENTS，返回动作说明。"""
    data, flags, hsize, items, end = parse(path)

    for bit, val, start, stop in items:
        if bit != F_ARGS:
            continue
        if ARG_FLAG in val:                     # 已经挂过
            return "already"
        new_str = f"{val} {arg}".strip()        # 保留原有参数，追加我们的
        blob = struct.pack("<H", len(new_str)) + new_str.encode("utf-16-le")
        _backup(path)
        path.write_bytes(data[:start] + blob + data[stop:])
        return "updated"

    # 没有 ARGUMENTS 段：StringData 的顺序固定为 名称 → 相对路径 → 工作目录 → 参数 → 图标
    insert_at = None
    for bit, _val, _start, stop in items:
        if bit in (F_NAME, F_RELPATH, F_WORKDIR):
            insert_at = stop
    if insert_at is None:                       # 只剩图标段时，参数要插在图标之前
        icon = [it for it in items if it[0] == F_ICON]
        insert_at = icon[0][2] if icon else end

    blob = struct.pack("<H", len(arg)) + arg.encode("utf-16-le")
    out = bytearray(data[:insert_at] + blob + data[insert_at:])
    struct.pack_into("<I", out, 0x14, flags | F_ARGS)

    _backup(path)
    path.write_bytes(bytes(out))
    return "patched"


def restore(path: Path) -> str:
    bak = path.with_suffix(".lnk.bak")
    if not bak.exists():
        return "no-backup"
    shutil.copy2(bak, path)
    return "restored"


def main() -> int:
    ap = argparse.ArgumentParser(description="给 BrowserOS neo 快捷方式加 --load-extension")
    ap.add_argument("--check", action="store_true", help="只检查不修改")
    ap.add_argument("--restore", action="store_true", help="从备份还原快捷方式")
    args = ap.parse_args()

    if not (PLUGIN_DIR / "manifest.json").exists():
        print(f"✗ 插件源缺失：{PLUGIN_DIR}")
        return 2
    arg = f'{ARG_FLAG}"{PLUGIN_DIR}"'

    links = find_shortcuts()
    if not links:
        print("✗ 没找到 BrowserOS neo 的快捷方式（桌面/开始菜单/任务栏）")
        return 3

    print(f"插件：{PLUGIN_DIR}")
    print(f"参数：{arg}\n")
    for p in links:
        if args.restore:
            print(f"  {restore(p):8s} {p}")
            continue
        cur = current_args(p)
        if args.check:
            mark = "已挂" if ARG_FLAG in cur else "未挂"
            print(f"  [{mark}] {p}")
            if cur:
                print(f"          现有参数: {cur[:100]}")
            continue
        act = patch(p, arg)
        print(f"  {act:8s} {p}")

    if not args.check and not args.restore:
        print("\n✓ 完成。**完全退出 BrowserOS neo 再重新打开**，插件就会自动加载。")
        print("  当前这次会话可先跑：python scripts\\ensure_extension.py --load")
    return 0


if __name__ == "__main__":
    sys.exit(main())
