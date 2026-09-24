# 在桌面创建「启动智客服」快捷方式（绝对路径 + 图标，与包内位置无关）。
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

$desktop = [Environment]::GetFolderPath("Desktop")
$linkPath = Join-Path $desktop $ShortcutName
if (Test-Path -LiteralPath $linkPath) { Remove-Item -LiteralPath $linkPath -Force }

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($linkPath)
$lnk.TargetPath = $target
$lnk.WorkingDirectory = $dir
$lnk.Description = $Description

$icon = Join-Path $dir $IconRel
if (Test-Path -LiteralPath $icon) { $lnk.IconLocation = "$icon,0" }

$lnk.Save()

if (-not (Test-Path -LiteralPath $linkPath)) { throw "桌面快捷方式创建失败" }
Write-Host ("  已创建: {0}" -f $linkPath)
