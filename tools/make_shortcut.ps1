# 生成绿色版启动快捷方式。快捷方式与 run.bat 同目录，整包解压/移动到任意路径后依然有效。
param(
  [Parameter(Mandatory = $true)][string]$Dir,
  [string]$Target = "run.bat",
  [string]$ShortcutName = "启动智客服.lnk",
  [string]$IconRel = "assets\app.ico",
  [string]$Description = "智客服 · AI 电商客服 Agent 平台（双击启动）"
)

$ErrorActionPreference = "Stop"

$dir = (Resolve-Path -LiteralPath $Dir).Path
$target = Join-Path $dir $Target
if (-not (Test-Path -LiteralPath $target)) {
  throw "未找到启动脚本: $target"
}

$linkPath = Join-Path $dir $ShortcutName
if (Test-Path -LiteralPath $linkPath) { Remove-Item -LiteralPath $linkPath -Force }

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($linkPath)
$lnk.TargetPath = $target
# 起始位置必须留空：Windows 会自动使用快捷方式所在目录，整包移动后仍能定位 run.bat
$lnk.WorkingDirectory = ""
$lnk.Description = $Description

$icon = Join-Path $dir $IconRel
if (Test-Path -LiteralPath $icon) { $lnk.IconLocation = "$icon,0" }

$lnk.Save()

if (-not (Test-Path -LiteralPath $linkPath)) { throw "快捷方式创建失败" }
Write-Host ("  shortcut ok -> {0}" -f $ShortcutName)
