# 本技能可用的脚本

| 文件 | 用途 | 底层实现 |
|---|---|---|
| `run_pipeline.py` | **批量下载带货短视频 + 去水印**（整条流水线） | `D:\Data\DouDian\scripts\run_pipeline.py` |
| `clean_output.py` | **删除本地已下载视频**（清空 带货短视频 目录） | `D:\Data\DouDian\scripts\clean_output.py` |
| `compass_video_rank.py` | 只打开罗盘短视频榜页面（不下载） | 本目录原生实现（非转发） |

## 说明

前两个是**转发脚本**，只把参数原样交给 `D:\Data\DouDian\scripts\` 下的真实实现，
所以不存在“两份代码不同步”的问题。真实实现还包括：

- `fetch_rank.py` —— 抓榜单商品与视频直链（`商品数据\短视频榜单_抓取.json`）
- `download_rank_videos.py` —— 按商品名建文件夹下载
- `batch_run.py` —— 批量去水印（调用 `video-cleaner\scripts\dewatermark.py`）

## 解释器

- `run_pipeline.py` / `clean_output.py` / `fetch_rank.py` / `download_rank_videos.py`：纯标准库，
  用 `D:\Install\Python\python.exe`
- 去水印那步必须用 `D:\Data\DouDian\video-cleaner\.venv\Scripts\python.exe`（需要 cv2 + torch），
  `run_pipeline.py` 内部会自动切换，外部调用时不用管。

## 典型调用

```bash
# 下载第 10-15 名（下载完自动去水印）
D:\Install\Python\python.exe run_pipeline.py --from 10 --to 15

# 只下载不处理
D:\Install\Python\python.exe run_pipeline.py --from 10 --to 15 --no-clean

# 删除本地视频
D:\Install\Python\python.exe clean_output.py --yes
```
