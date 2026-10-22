# 重新加载「晓风运营插件」到 BrowserOS neo
#
# 用途：电脑重启后未打包扩展经常不自动加载，导致罗盘页面缺少 itemid 属性、
#       fetch_rank.py 抓到 0 个商品。运行本脚本即可恢复。
#
# 用法（在项目根目录执行）：
#   powershell -ExecutionPolicy Bypass -File scripts\fix_extension.ps1
#
# 前置：BrowserOS neo 正在运行（CDP 端口 9110 可访问）

$ErrorActionPreference = 'Continue'
$PluginPath = 'D:\Data\DouDian\插件\晓风运营插件-30.3.3'
$CdpPort = 9110
$ExpectedId = 'oiinpblopagmgmihimfcfjpcdfimegme'

Write-Output "=== 检查插件源目录 ==="
if (-not (Test-Path (Join-Path $PluginPath 'manifest.json'))) {
    Write-Output "[X] 找不到 $PluginPath\manifest.json"
    Write-Output "    源目录不能移动/删除，未打包扩展按路径引用。请从 git 仓库恢复。"
    exit 1
}
Write-Output "OK: $PluginPath"

Write-Output ""
Write-Output "=== 连接 CDP $CdpPort ==="
try {
    $ver = Invoke-RestMethod "http://127.0.0.1:$CdpPort/json/version" -TimeoutSec 8
} catch {
    Write-Output "[X] 连不上 CDP $CdpPort，BrowserOS neo 可能没启动。"
    exit 2
}
Write-Output "Browser: $($ver.Browser)"

$ws = New-Object System.Net.WebSockets.ClientWebSocket
$ct = [System.Threading.CancellationToken]::None
try {
    $ws.ConnectAsync([Uri]$ver.webSocketDebuggerUrl, $ct).Wait(10000)
    if ($ws.State -ne 'Open') { throw "WebSocket 状态异常: $($ws.State)" }

    $msg = '{"id":1,"method":"Extensions.loadUnpacked","params":{"path":"' + $PluginPath.Replace('\','\\') + '"}}'
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($msg)
    $seg = New-Object 'System.ArraySegment[byte]' -ArgumentList @(,$bytes)
    $ws.SendAsync($seg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $ct).Wait(10000)

    $buf = New-Object byte[] 8192
    $seg2 = New-Object 'System.ArraySegment[byte]' -ArgumentList @(,$buf)
    $task = $ws.ReceiveAsync($seg2, $ct)
    if (-not $task.Wait(15000)) { throw "等待响应超时" }
    $resp = [System.Text.Encoding]::UTF8.GetString($buf, 0, $task.Result.Count)
    Write-Output "响应: $resp"

    if ($resp -match $ExpectedId) {
        Write-Output ""
        Write-Output "[OK] 插件已加载（扩展 ID $ExpectedId）"
        Write-Output ""
        Write-Output "最后一步：已打开的罗盘页面需要刷新一次，插件才会注入。"
        Write-Output "  执行：D:\Install\Python\python.exe D:\Data\DouDian\scripts\reload_page.py"
        Write-Output "  或者手动刷新浏览器里的榜单页。"
    } else {
        Write-Output ""
        Write-Output "[!] 返回里没有预期扩展 ID，请到 chrome://extensions 手动确认。"
        exit 3
    }
} catch {
    Write-Output "[X] 加载失败: $($_.Exception.Message)"
    Write-Output "    可在 chrome://extensions 里开开发者模式，手动「加载未打包的扩展程序」。"
    exit 4
} finally {
    if ($ws.State -eq 'Open') { $ws.Dispose() }
}
