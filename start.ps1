$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "找不到虚拟环境。请先阅读 README.md 的安装步骤。"
}
& $python (Join-Path $project 'bot.py') serve
