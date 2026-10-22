# 抖音短视频水印清除（本地 AI）

在本地用 **LaMa（Large Mask Inpainting）** 模型清除抖音下载视频上的水印（抖音 logo、"抖音号：xxx"、搜索框），
全程离线运行，不上传任何视频。

---

## 一、目录说明

```
D:\Data\DouDian\video-cleaner\
├── input\            放待处理的视频（也可以直接拖到 run.bat 上）
├── output\           成品输出目录
├── frames\           调试用的抽帧 / 对比图（可随时删除）
├── models\           模型权重
│   ├── lama_fp32.onnx    LaMa ONNX（CPU 推理用）
│   └── big-lama.pt       LaMa TorchScript（GPU 推理用）
├── tools\
│   └── ffmpeg-master-latest-win64-gpl\   便携版 ffmpeg（无需安装）
├── scripts\
│   ├── dewatermark.py    主程序
│   ├── probe.py          查看视频信息 / 抽帧
│   ├── sheet.py          生成水印位置联系表
│   └── download_multi.py 多线程下载器
├── .venv\            Python 虚拟环境（已装 opencv / onnxruntime）
├── setup_env.py      换机后一键重建运行环境
├── run.bat           一键运行
└── README.md         本文件
```

---

## 一之二、换机 / 重装后怎么恢复

项目用 git 管理，但**不包含**下列内容——它们合计约 5GB，且全部可以从代码和公开源重建：

| 内容 | 体积 | 恢复方式 |
|---|---|---|
| `.venv/` | 4.3G | `setup_env.py` 自动创建并装依赖 |
| `tools/`（ffmpeg） | 497M | `setup_env.py` 自动下载解压 |
| `models/lama_fp32.onnx` | 208M | `setup_env.py` 从 hf-mirror 下载并校验 SHA256 |
| `models/big-lama.pt` | 205M | **需从旧机器拷贝**（公开源只有原始 .ckpt） |
| `input/` `output/` `frames/` | 93M | 测试素材与产物，无需恢复 |

**一条命令补齐**：

```bat
D:\Install\Python\python.exe D:\Data\DouDian\video-cleaner\setup_env.py
```

脚本幂等，已存在的步骤自动跳过；最后会做一遍环境自检（opencv / numpy / torch / 模型 / ffmpeg）。

**关于 `big-lama.pt`**：公开源（hf-mirror 的 `smartywu/big-lama`）只提供原始的
`best.ckpt`，本工具用的是转好的 TorchScript 版本，所以这个文件只能从旧机器拷贝。
没有它也能跑——`dewatermark.py` 会退回 ONNX(CPU) 后端，只是慢约 35 倍。

**为什么这些不进 git**：GitHub 单文件上限 100MB，205MB 的 `big-lama.pt` 和 208MB 的
`lama_fp32.onnx` 直接推不上去；`.venv` 含数万个小文件，git 按快照存储，每次依赖变动都会
新增一份完整副本，仓库会从 1.2MB 涨到 5GB+，clone 和 status 都会变得很慢。
如果用 Git LFS，5GB 也超出免费额度。所以代码走 git、依赖走重建脚本，是这里更合适的划分。

---

## 二、怎么用

### 方式 1：双击 `run.bat`
会把 `input\` 目录下所有 mp4 依次处理，成品写到 `output\`。

### 方式 2：把视频拖到 `run.bat` 图标上
只处理拖入的那一个文件。

### 方式 3：命令行（可调参数）

```bat
cd /d D:\Data\DouDian\video-cleaner
.venv\Scripts\python.exe scripts\dewatermark.py -i input\v1.mp4 -o output
```

常用参数：

| 参数 | 说明 |
|---|---|
| `-i` | 输入视频或目录 |
| `-o` | 输出目录（默认 `output\`） |
| `--backend` | `auto`（默认，优先 GPU）/ `torch` / `onnx` / `cpu` / `dml` |
| `--limit N` | 只处理前 N 帧，用来快速试效果 |
| `--trim-tail 1.5` | 裁掉片尾 1.5 秒（抖音推荐页/关注引导那一屏） |
| `--mask-scale 1.2` | 把遮挡框放大 20%，水印贴边或有光晕时用 |
| `--extra-mask "x0,y0,x1,y1,起秒,止秒"` | 强制补遮一块区域，可重复；专门对付极淡、位置随机的 `@昵称` 水印 |
| `--no-at` | 关闭 `@昵称` 自动检测（改用 `--extra-mask` 手动指定） |

---

## 三、它是怎么工作的

1. **逐帧定位**：抖音水印是半透明白色叠加层。程序取 `min(R,G,B)` 得到"白度图"，
   再用一张模板（`抖音号：nimo520520` 那一行文字）做**多尺度模板匹配**，
   每帧都能找到水印当前的位置——水印会在屏幕角落之间跳动，所以必须逐帧定位。
2. **时间平滑**：对连续帧的命中坐标做中值滤波，避免个别误检导致遮挡框抖一下。
3. **生成遮挡 mask**：按水印整块（logo + 抖音号 + 搜索框）画矩形。
4. **自动精修遮挡框**：不同版本的抖音水印排版不一样（logo 行距文字行 77px 或 120px），
   程序会在命中点周围用"白度顶帽"扫描水印信号，让框自己长到刚好盖住整块水印。
5. **片尾自动截断**：抖音视频结尾常有一屏「抖音推荐页/关注引导」UI，它会让模板误命中到画面中央。
   程序按"是否贴四个角"过滤这类命中，并把尾巴上连续的 UI 帧整段裁掉。
6. **LaMa 修复**：以水印为中心取 512×512 窗口送进模型，模型根据周围纹理**重建**被遮住的像素
   （木纹、墙面、编织物、瓷砖缝都能接上），再按 mask 羽化贴回原图。
7. **合成**：处理后的帧通过管道直接喂给 ffmpeg，一次性编码 H.264 并**保留原音轨**，无二次压缩损失。

---

## 四、另一种水印：半透明的 `@昵称`

抖音除了「logo + 抖音号 + 搜索框」那一整块，还会叠加一行很淡的 `@昵称`（比如 `@没脾气的尼莫`）。
它对比度极低（半透明压在木地板/白色猫窝上），**没有可用的自动检测特征**——
模板匹配、白度顶帽、饱和度、描边判别都试过，正负样本分数完全重叠。

所以这类水印用 `--extra-mask` 手动指定。本项目三个视频的实测参数：

```bat
:: v1（约 22.4 秒起出现）
python scripts\dewatermark.py -i input\v1.mp4 -o output --no-at ^
  --extra-mask "0,816,235,892,22.4,30"

:: v2（约 10.6 秒起出现，位置略靠右）
python scripts\dewatermark.py -i input\v2.mp4 -o output --no-at ^
  --extra-mask "55,842,265,903,10.6,33"
```

**怎么为新视频找参数**：抽一帧含该水印的画面 → 放大画 10px 网格（`frames\g_v1.png` 就是这种图）
→ 读出文字的 x0,y0,x1,y1 → 起点秒数用「逐帧抽看第一次出现的帧号 ÷ fps」。

---

## 五、效果预期

- 水印在**平坦或有规律纹理**的背景（木地板、墙面、天空、纯色布景）上：几乎看不出修复痕迹。
- 水印压在**复杂前景**（植物枝叶、人脸、细密文字）上时：LaMa 会合理"猜"一个背景，
  可能与该处真实内容略有差异，但不会留下水印残影。
- 水印本身半透明，被完全遮盖的区域信息已丢失，任何修复都是模型推测，这一点无解。

---

## 六、常见问题

**Q：处理一个视频要多久？**（本机 RTX 4070 Ti SUPER 实测）
- GPU（LaMa-Torch，默认走这条）：30 秒视频约 2 分钟，其中检测占 1.5 分钟、修复只用 40 秒
- CPU（LaMa-ONNX，`--backend onnx`）：同样视频约 18 分钟

**Q：输出的视频为什么比原片短了 1~3 秒？**
末尾那段是抖音的推荐页 UI（头像、搜索框、"来抖音发现更多创作者"），不是视频内容，
程序会自动识别并裁掉。想保留可以用 `--trim-tail 0` 之外的方式手动控制，或参考脚本里的
`_corner_ok` 过滤逻辑。

**Q：输出视频有音轨吗？**
有，直接复用原视频的音轨（`-c:a copy`，无损）。

**Q：能当手机壁纸用吗？**
输出是标准 H.264 mp4。安卓可用「动态壁纸」类 App 直接选用；
iPhone 需要先转成 Live Photo（可用「壁纸制作」类 App 转换）。

**Q：换其他账号的水印能用吗？**
可以，但要重新制作模板：从新视频里截一帧含"抖音号：xxx"的图，
改 `scripts\dewatermark.py` 里的 `TEMPLATE` 路径和 `TPL_BOX`（模板文本框坐标）即可。

**Q：只是想去水印、不想装环境？**
`tools\` 里已带 ffmpeg 便携版，也可以直接用 `delogo` 滤镜（快但边缘会糊）：

```bat
tools\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe -i input\v1.mp4 ^
  -vf "delogo=x=436:y=1090:w=280:h=190" -c:a copy output\v1_delogo.mp4
```
