<#
.SYNOPSIS
    Rotate the read-only API token used by mcp_bridge.py without exposing it on the command line.

.DESCRIPTION
    Windows keeps command history, so a token typed as an argument can leak.
    This script reads the new token as a secure prompt, checks it against the running
    server, and only then stores it as the user-scope ASSET_API_TOKEN variable.
    Nothing is written when the token is rejected.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\set-token.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\set-token.ps1 -ServerUrl http://10.10.40.190:8750
#>
param(
    [string]$ServerUrl = 'http://127.0.0.1:8750',
    [switch]$SkipVerify
)
$ErrorActionPreference = 'Stop'

function Test-Token($value) {
    $headers = @{ Authorization = 'Bearer ' + $value }
    try {
        # /api/images proves the token can read assets; /api/status never checks the token.
        $response = Invoke-WebRequest -Uri ($ServerUrl.TrimEnd('/') + '/api/images?limit=1') -Headers $headers -UseBasicParsing -TimeoutSec 15
        return @{ Ok = $true; Total = ($response.Content | ConvertFrom-Json).total }
    } catch {
        $status = $null
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        return @{ Ok = $false; Status = $status }
    }
}

Write-Host "素材库地址：$ServerUrl"

if (-not $SkipVerify) {
    $probe = $null
    try {
        $probe = Invoke-WebRequest -Uri ($ServerUrl.TrimEnd('/') + '/api/status') -UseBasicParsing -TimeoutSec 10
    } catch {
        throw "无法连接 $ServerUrl，请先运行 start.ps1 启动服务。"
    }
    if (-not ($probe.Content | ConvertFrom-Json).configured) {
        throw '素材库尚未初始化管理员账号，请先在网页完成初始化。'
    }
}

$secure = Read-Host -Prompt '请粘贴新的只读令牌（输入不会回显到屏幕）' -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    $token = $token.Trim()
    if (-not $token) { throw '令牌为空，未做任何修改。' }
    if ($token -notmatch '^img_') { throw '令牌格式不正确：应以 img_ 开头。' }

    $previous = [Environment]::GetEnvironmentVariable('ASSET_API_TOKEN', 'User')
    if ($previous -eq $token) {
        Write-Host '新令牌与当前使用的令牌相同，无需修改。' -ForegroundColor Yellow
        return
    }

    if (-not $SkipVerify) {
        $check = Test-Token $token
        if (-not $check.Ok) {
            if ($check.Status -eq 401) { $hint = '令牌无效、已被撤销，或复制不完整。' }
            elseif ($check.Status) { $hint = "服务返回 $($check.Status)。" }
            else { $hint = '无法连接服务。' }
            throw "验证未通过：$hint 未修改环境变量。"
        }
        Write-Host "令牌验证通过，可读取 $($check.Total) 张图片。" -ForegroundColor Green
    }

    [Environment]::SetEnvironmentVariable('ASSET_API_TOKEN', $token, 'User')
    [Environment]::SetEnvironmentVariable('ASSET_SERVER_URL', $ServerUrl, 'User')
    if (-not [Environment]::GetEnvironmentVariable('ASSET_EXPORT_DIR', 'User')) {
        [Environment]::SetEnvironmentVariable('ASSET_EXPORT_DIR', (Join-Path $PSScriptRoot 'exports'), 'User')
    }

    Write-Host '已更新用户环境变量 ASSET_API_TOKEN。' -ForegroundColor Green
    if ($previous) {
        Write-Host '旧令牌已从本机环境变量中移除；如仍在别处使用，请到网页「AI 取图」撤销它。'
    }
    Write-Host ''
    Write-Host '需要重启 MCP 客户端（Cursor / VS Code / Claude Code 等）才会读到新令牌。'
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
