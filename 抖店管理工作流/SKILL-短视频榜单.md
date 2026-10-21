---
name: compass-video-rank
description: 自动打开抖店电商罗盘「短视频榜单」目标页——商品榜单→短视频榜→母婴宠物/宠物生活类目→非知名品牌。当用户说"打开短视频页面""打开短视频榜单""看看爆火带货短视频""筛选爆火短视频""罗盘短视频榜"时使用。必须直接运行现成脚本，不要手工操作浏览器。
---

# 抖店电商罗盘 · 爆火带货短视频筛选

## ⚠️ 执行方式（最重要，先读这段）

**这个技能的全部工作都封装在 Python 脚本里。你的唯一任务是执行下面这条命令。**

```bash
D:/Install/Python/python.exe C:/Users/18210/.openclaw/workspace/skills/doudian-export/scripts/compass_video_rank.py
```

用 `bash` 工具执行这条命令，等待结束（约 40 秒），然后把输出里的
`RESULT_PAGE=<页面id>` 报给用户。**这就完成了。**

页面默认**保留打开**，用户可以直接查看榜单。加 `--close-after` 才会关闭。

### 汇报方式（严格遵守，直接影响用户等待时间）

脚本跑完后，**只回一句话**，不要加任何其他内容：

```
已进入短视频榜单：短视频榜 / 非知名品牌 / 母婴宠物·宠物生活
```

**禁止在脚本成功后做任何额外动作**：

- ❌ 不要再去 snapshot 确认页面状态——脚本输出的最终状态就是结果
- ❌ 不要写总结、复盘、原理说明或"接下来建议"
- ❌ 不要重新执行脚本"以确保成功"

> **原因**：本地模型（Qwen3.5-9B）是推理模型，写长回复会消耗大量思考
> token 让用户白等。任务已完成的情况下，一句话汇报即可。

### 绝对不要做的事

- ❌ **不要**自己调用 `browseros-neo__act` / `snapshot` / `tabs` 去点
  「市场」「商品榜单」「短视频榜」等按钮。脚本内部已封装全部浏览器操作。
- ❌ **不要**自己尝试「先获取快照再用 act 点击」这类手工流程。
- ❌ **不要**因为脚本某一步报错就改用浏览器工具绕过。先看报错内容。

## 脚本做了什么

进入抖店后台 → 直达电商罗盘商品榜单页 → 选中「短视频榜」tab
→ 选中「非知名品牌」→ 确认类目为「母婴宠物/宠物生活」。

关键实现（已实测验证）：

- **直达 URL**：`https://compass.jinritemai.com/shop/chance/rank-product`
  登录态下直接打开就是商品榜单页，页面会记住上次的类目选择。
- **榜单 tab**：通过 snapshot 拿 `tab "短视频榜"` 的 ref，用 `act` 点击。
  选中态看祖先链 `aurora-tabs-tab-active` 类名。
- **品牌开关**：`非知名品牌` 是 `div.tagItem-*` 组件，用 DOM `el.click()` 触发，
  选中后叶子节点 class 变为 `tagItem-Kca1ie activeItem-eBkSoc`。
  同时排除「知名品牌」，确保只保留非知名品牌。
- **罗盘登录态**：`compass.jinritemai.com` 根路径是营销官网页，无独立登录态，
  必须先经 `fxg.jinritemai.com` 登录唤醒会话，再开罗盘页。

## 前置条件

1. 浏览器必须已登录抖店（`fxg.jinritemai.com`）。登录态失效时脚本会明确报错。
2. browseros-neo MCP 需在 `http://127.0.0.1:9010/mcp` 监听。
3. Python 解释器在 `D:\Install\Python\python.exe`（不要用 `python`，系统 PATH 里没有）。

## 参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--close-after` | 运行结束后关闭页面 | 关（**默认保留**，便于直接看榜单） |
| `--skip-login` | 跳过登录入口直接进后台 | 关 |

## 两种触发方式

### 1. 定时任务（已配置，每天 09:30）

| 项目 | 值 |
|---|---|
| 任务名 | 抖店短视频榜单-每日 |
| 任务 ID | `21378f2a-fd17-46b1-bdf9-b9774f15b5c9` |
| 时间 | 每天 09:30（cron `30 9 * * *`，Asia/Shanghai） |
| 状态 | enabled |

```bash
openclaw automations list                                   # 查看下次执行时间
openclaw automations run 21378f2a-fd17-46b1-bdf9-b9774f15b5c9   # 立即手动触发
openclaw automations runs 21378f2a-fd17-46b1-bdf9-b9774f15b5c9  # 查看运行历史
```

实测：触发后约 37 秒完成，status=ok，exitCode=0，页面留在目标筛选状态。

### 2. 手动呼唤

用户在 OpenClaw 对话里说「打开短视频页面」「打开短视频榜单」
「看看爆火带货短视频」等，即触发本技能，执行上面那条命令即可。

如果用户只是问"几点跑/跑得怎么样"，查任务状态，**不用执行脚本**。

## 页面清理机制

每次运行会：

1. 先关掉上次遗留的榜单页（URL 含 `/shop/chance/rank-product` 的页面）
2. 关掉登录入口页
3. 开榜单页后立即关掉登录探测用的商品管理页
4. 运行结束**保留榜单页**供查看

因此每天只会留 1 个榜单页，不会累积。

## 常见失败

| 报错 | 原因 | 处理 |
|---|---|---|
| `抖店登录态已失效` | 登录过期 | 让用户在浏览器里登录抖店，再重跑 |
| `等待榜单 tab「短视频榜」超时` | 页面渲染慢或未登录 | 确认登录态，隔几秒重跑 |
| `MCP 连接失败` | browseros-neo 没启动 | 确认 9010 端口有服务 |

遇到失败**如实报告给用户**，并给出上表对应的处理建议。
不要自行绕过、不要反复重试超过 2 次。

## 维护信息（仅在用户要求修改代码时才需要读）

脚本：`scripts/compass_video_rank.py`，纯标准库，复用
`doudian_export.py` 的 McpSession（登录态、断线重连、页面清理）。

已处理的坑（改代码前必读）：

- **SSE 多帧解析**：browseros 的 streamable-http 返回多个 `data:` 帧，
  `RobustSession._post` 按 id 扫描全部帧取对应 JSON，否则 `tabs` 等调用
  会返回 None。
- **evaluate 参数**：`code` 参数按语句执行不返回表达式值，取返回值用
  `func` 参数（箭头函数）。
- **untrusted 包裹**：evaluate 结果被 `[UNTRUSTED_PAGE_CONTENT]` 包裹，
  `js_eval` 剥掉标记行再取 JSON。
- **选中态判定**：榜单 tab 的 active 类在祖先层（`aurora-tabs-tab-active`），
  品牌 tag 的 active 在叶子节点自身（`activeItem-eBkSoc`），两者判定方式不同，
  不能混用。
- **DOM 合成事件**：对抖店/罗盘的 React 菜单路由无效，但品牌 tag 的
  `el.click()` 有效。菜单跳转要依赖 URL 直达或 snapshot 拿 ref 用 act。
