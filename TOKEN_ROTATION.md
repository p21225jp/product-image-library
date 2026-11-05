# 更换只读访问令牌

给 AI / MCP 取图工具使用的只读令牌（`ASSET_API_TOKEN`）需要轮换时，按本文操作。

## 什么时候需要更换

- 令牌被发到聊天、邮件、截图、共享文档里
- 同事离职或不再需要访问
- 怀疑令牌泄露（审计日志里出现异常读取）

令牌一旦泄露，**拿到字符串的人不需要账号密码就能下载全部图片**，应立即撤销。

## 操作步骤

### 1. 在网页撤销旧令牌并新建

1. 浏览器打开 `http://127.0.0.1:8750`，用**管理员账号**登录
2. 左侧进入「AI 取图」
3. 找到旧的令牌，点撤销
4. 点「创建令牌」，起一个能看出用途的名字，例如 `张三的取图工具`
5. 新令牌**只显示一次**，复制它

### 2. 在本机写入环境变量

在项目目录下运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\set-token.ps1
```

脚本会：

1. 确认服务在运行、管理员已完成初始化
2. 提示粘贴新令牌 —— **输入不会显示在屏幕上**，也不会进入命令历史
3. 用 `/api/images` 实测令牌能否读到图片（只查响应，不下载内容）
4. **验证通过才写入**用户级环境变量 `ASSET_API_TOKEN`；验证失败则完全不做修改
5. 同时确保 `ASSET_SERVER_URL`、`ASSET_EXPORT_DIR` 已配置

如果服务不在本机默认地址，加参数：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\set-token.ps1 -ServerUrl http://10.10.40.190:8750
```

### 3. 重启 MCP 客户端

环境变量只在新启动的进程里生效。必须**完全退出并重新打开** Cursor / VS Code / Claude Code 等客户端，令牌才会被读取。

## 验证新令牌可用

```powershell
$env:ASSET_API_TOKEN = [Environment]::GetEnvironmentVariable('ASSET_API_TOKEN','User')
$env:ASSET_SERVER_URL = [Environment]::GetEnvironmentVariable('ASSET_SERVER_URL','User')
$h = @{ Authorization = 'Bearer ' + $env:ASSET_API_TOKEN }
(Invoke-WebRequest -Uri ($env:ASSET_SERVER_URL + '/api/images?limit=1') -Headers $h -UseBasicParsing).Content
```

返回图片列表 JSON 且 `total` 正常，说明新令牌可用。

## 为什么不用 `setx` 或直接在命令行写令牌

- `setx` 的参数会留在 PowerShell 命令历史（`Get-History`、`ConsoleHost_history.txt`）里
- 命令行参数也会出现在进程列表、终端回滚缓冲、截图和录屏中
- `set-token.ps1` 使用 `Read-Host -AsSecureString`，令牌只存在于内存，且先验证后写入

## 关于环境变量的作用范围

| 范围 | 谁能读到 | 本脚本使用 |
|---|---|---|
| 用户级（User） | 当前 Windows 账号下新启动的进程 | 是 |
| 系统级（Machine） | 本机所有账号 | 否，不需要管理员权限 |
| 进程级（Process） | 仅当前进程 | 否，关闭窗口即失效 |

同事在自己的电脑上使用，需要在**那台电脑**上单独执行本脚本，并把 `-ServerUrl` 改成服务器的内网地址。

## 相关文件

- `mcp_bridge.py` —— 读取 `ASSET_SERVER_URL`、`ASSET_API_TOKEN`、`ASSET_EXPORT_DIR`
- `set-token.ps1` —— 本流程使用的中文交互式设置脚本
- `exports/` —— `ASSET_EXPORT_DIR` 默认指向的图片导出目录
