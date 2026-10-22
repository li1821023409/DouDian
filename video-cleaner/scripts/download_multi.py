"""多线程分段下载大文件（绕开单连接限速）。"""
import os
import sys
import threading
import time
import urllib.request

URL = sys.argv[1]
OUT = sys.argv[2]
THREADS = int(sys.argv[3]) if len(sys.argv) > 3 else 8


def head_size(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers["Content-Length"])


def main():
    total = head_size(URL)
    print(f"总大小 {total/1e6:.1f} MB，{THREADS} 线程")
    part = total // THREADS
    done = [0] * THREADS
    lock = threading.Lock()

    # 预分配文件
    with open(OUT, "wb") as f:
        f.truncate(total)

    def worker(i):
        start = i * part
        end = total - 1 if i == THREADS - 1 else (i + 1) * part - 1
        req = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}"})
        got = start
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=60) as r, open(OUT, "r+b") as f:
                    f.seek(got)
                    while got <= end:
                        chunk = r.read(262144)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        with lock:
                            done[i] = got - start
                break
            except Exception as e:
                print(f"  线程{i} 重试{attempt}: {e}")
                time.sleep(2)
        done[i] = got - start

    ths = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(THREADS)]
    t0 = time.time()
    for t in ths:
        t.start()
    while any(t.is_alive() for t in ths):
        time.sleep(2)
        cur = sum(done)
        el = time.time() - t0
        print(f"  {cur/1e6:.0f}/{total/1e6:.0f} MB  {cur/el/1e6:.2f} MB/s", end="\r")
    for t in ths:
        t.join()
    el = time.time() - t0
    size = os.path.getsize(OUT)
    print(f"\n完成 {size/1e6:.1f} MB / {total/1e6:.1f} MB  用时 {el:.0f}s  "
          f"平均 {size/el/1e6:.2f} MB/s")


if __name__ == "__main__":
    main()
