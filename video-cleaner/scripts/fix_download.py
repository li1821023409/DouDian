"""修复多线程下载留下的空洞：扫描全零块并重新下载补齐。"""
import sys
import urllib.request

URL = sys.argv[1]
PATH = sys.argv[2]
BLOCK = 1024 * 1024

import os
total = os.path.getsize(PATH)

# 1. 找出全零块
holes = []
with open(PATH, "rb") as f:
    idx = 0
    while True:
        chunk = f.read(BLOCK)
        if not chunk:
            break
        if not any(chunk):
            holes.append((idx * BLOCK, idx * BLOCK + len(chunk) - 1))
        idx += 1

print(f"文件 {total/1e6:.1f} MB，发现 {len(holes)} 个全零块（{sum(h-e+1 for h,e in holes)/1e6:.1f} MB）")
if not holes:
    print("无需修复")
    sys.exit(0)

# 2. 合并相邻洞
merged = []
for h, e in holes:
    if merged and h <= merged[-1][1] + 1:
        merged[-1] = (merged[-1][0], e)
    else:
        merged.append((h, e))
print(f"合并为 {len(merged)} 段")

# 3. 逐段补下
with open(PATH, "r+b") as f:
    for i, (h, e) in enumerate(merged):
        got = h
        for attempt in range(4):
            try:
                req = urllib.request.Request(URL, headers={"Range": f"bytes={got}-{e}"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    f.seek(got)
                    while got <= e:
                        b = r.read(262144)
                        if not b:
                            break
                        f.write(b)
                        got += len(b)
                break
            except Exception as ex:
                print(f"  段{i} 重试{attempt}: {ex}")
        print(f"  段{i} {(h)/1e6:.0f}-{e/1e6:.0f} MB -> 写到 {got/1e6:.1f} MB "
              f"({'OK' if got > e else '未完成'})")

# 4. 复查
holes2 = []
with open(PATH, "rb") as f:
    idx = 0
    while True:
        chunk = f.read(BLOCK)
        if not chunk:
            break
        if not any(chunk):
            holes2.append(idx * BLOCK)
        idx += 1
print(f"复查：剩余全零块 {len(holes2)} 个")
