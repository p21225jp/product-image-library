# 公司内网 / VPN 部署交接

目标：图片库运行在公司常开的服务器上，员工在公司内网或连接公司 VPN 后访问；数据库、原图、缩略图均保存在公司服务器的本地持久化磁盘。

本文和同目录文件是部署模板。尚未连接目标服务器，未安装服务、签发证书、修改 DNS、VPN 或防火墙。示例域名 `assets.company.example` 和目录必须由 IT 替换。

## IT 先确认这些信息

| 信息 | 需要填写的内容 |
| --- | --- |
| 系统 | Windows / Windows Server 或 Linux，具体版本 |
| 服务器 | 固定内网 IP、CPU、内存、可用磁盘空间 |
| 管理方式 | IT 代操作，或提供公司批准的远程维护方式；密码不要写入本说明 |
| 固定入口 | 公司管理的域名下的子域名，内网 DNS 指向服务器 IP |
| VPN | VPN 用户能够路由到服务器；VPN 连接下能解析同一个域名 |
| 证书 | 包含该域名的证书和私钥，员工电脑与 MCP Python 客户端信任签发 CA |
| 数据与备份 | 服务器本地数据目录、独立备份位置、保留时间及负责人员 |

仅作为容量规划起点，可考虑 2 核 / 4 GB 内存；正式容量以实际上传、缩略图处理和原图下载负载验证。磁盘需容纳原图、缩略图、临时 ZIP、增长空间；独立备份另计。

## 访问结构

```text
员工浏览器 / 员工电脑上的 MCP 取图工具
        │ 公司内网，或公司 VPN（DNS + 路由）
        ▼
https://公司分配的图库域名:443
        │ Caddy 或公司现有 HTTPS 反向代理
        ▼
127.0.0.1:8750  图片库（单进程）
        │
        └── 服务器本地数据目录
              library.sqlite3 / originals / thumbnails / temp
```

应用绑定 `127.0.0.1:8750`，员工通过 HTTPS 入口访问。IT 仅向所需公司网段及 VPN 网段放行 TCP 443，不配置公网端口映射。模板不依赖 HTTP 80；TLS 证书由公司提供。若公司已有代理，可按同样的 Host、转发头和初始化接口限制接入。

## 程序和数据迁移

1. 将源码包解压到服务器程序目录，重新建立 Python 虚拟环境并安装 `requirements.txt`。不复制开发电脑的 `.venv`。使用公司支持、且兼容本项目的 Python 3.10+；依赖安装可使用内部镜像或离线 wheel。Node.js 不是运行依赖。
2. 定好迁移时间，在最终备份前停止旧库上传、编辑、删除等写入。源电脑在相同的 `ASSET_DATA_DIR` 配置下运行现有备份命令，目的地使用一个尚不存在的新目录：

   ```powershell
   .\.venv\Scripts\python.exe manage.py backup 'D:\AssetBackups\migration-final'
   ```

   示例盘符需要替换。使用备份工具，不直接复制正在运行的 SQLite 文件。只有生成 `backup.json` 的备份才完整。
3. 经公司批准的内网传输方式，将完整备份目录复制到服务器的数据目录。程序和数据分开存放。SQLite 放本机磁盘，不能直接放 SMB/NAS 共享；独立备份可以放在公司受控备份存储。
4. 数据备份包含账号及令牌哈希，目标目录仅服务账号与维护人员可访问；登录会话已在备份中清空，迁移后员工重新登录。
5. 配置下文环境变量和 HTTPS，先让维护人员验收，再切换员工入口。验收前旧库继续停止写入，避免两边产生不同版本的数据。
6. 切换失败时先停止新库。若新库尚无业务写入，可恢复旧入口；若已经有新增或修改，先备份新库并核对差异，不能直接用旧备份覆盖。

全新空库才需要首次初始化：先仅绑定本机回环地址，不设置 `ASSET_DISABLE_SETUP=1`、HTTPS Origin 或 Secure Cookie，在服务器本机完成管理员初始化，再启用正式配置。从现有库迁移时无需重新创建管理员。

## 应用环境变量

| 变量 | 示例 / 作用 |
| --- | --- |
| `ASSET_DATA_DIR` | 实际持久化数据目录，包含 `library.sqlite3` |
| `ASSET_ALLOWED_HOSTS` | `assets.company.example`；只填域名，不含协议和路径 |
| `ASSET_PUBLIC_ORIGIN` | `https://assets.company.example`；账号管理中的分享地址与浏览器 Origin 校验使用此值 |
| `ASSET_COOKIE_SECURE` | `1`；正式入口仅通过 HTTPS 传递登录 Cookie |
| `ASSET_TRUSTED_PROXIES` | `127.0.0.1`；仅信任指定 IP 的代理头，以正确识别访问者并分别限流 |
| `ASSET_DISABLE_SETUP` | `1`；迁移或本机初始化完成后禁用首次管理员创建入口 |

`ASSET_TRUSTED_PROXIES` 允许逗号分隔的明确 IP，不接受 `*` 或网段。默认留空保持原有内网直连行为。使用同机代理时填写 `127.0.0.1`，不要把员工网段设成可信代理。当前启动器保持单进程，不直接扩展为多副本。

Python 不会自动加载 `.env`。Linux 由 systemd 的 `EnvironmentFile` 加载，Windows 由启动脚本设置。已有 `start.ps1 -LocalOnly` 也会继承同一 PowerShell 会话里的变量。

## HTTPS 入口

参照 `Caddyfile.example`，替换域名、证书链和私钥路径。Windows 路径用带引号的正斜杠形式，例如 `"D:/AssetLibrary/certs/fullchain.pem"`。

模板把所有业务请求转发到 `127.0.0.1:8750`，保留 Host，并拒绝通过代理访问 `/api/setup`。Caddy 会处理客户端转发头；应用仅信任上述指定代理。不要添加指向 `data`、原图或缩略图目录的静态文件路由，以免绕过账号鉴权。

实际机器安装 Caddy 后执行 `caddy validate --config 实际配置路径 --adapter caddyfile`。本机尚未安装或运行 Caddy，此处配置需在目标机器配合实际证书验证。若改用公司现有代理，保证上传限制不低于应用所需的 26 MiB 请求上限，并验证大图上传、原图和 ZIP 下载的超时配置。

证书更新由 IT 的签发流程负责，替换证书后重新验证并重载代理。客户端需信任公司 CA；不要通过关闭证书校验解决报错。代理本身也必须配置开机自启和异常重启。

## Windows / Windows Server

1. 在服务器程序目录用 `python -m venv .venv` 建立环境，再用 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` 安装依赖。
2. 将 `run-windows.example.ps1` 复制为同目录 `run-windows.ps1`，填写正式域名和数据目录，先手动运行验证。脚本只绑定回环地址，并要求数据目录已经恢复或初始化。
3. IT 在任务计划程序中使用专用服务账号配置“系统启动时”触发、“不管用户是否登录都运行”，动作是：

   ```text
   程序：powershell.exe
   参数：-NoProfile -ExecutionPolicy Bypass -File "实际程序目录\deploy\run-windows.ps1"
   ```

   设置失败后重启、禁止重复实例、取消“运行超过指定时长则停止”的限制；不勾选仅空闲时运行。使用公司策略要求的脚本签名 / 执行策略时调整参数。服务账号只需要程序读取、数据目录读写和所需备份权限。任务无须管理员身份运行。
4. 将 Caddy 注册为公司批准的后台服务，配置日志收集与保留时间。也可由 IT 的现有服务管理工具托管应用及代理。
5. 重启服务器，验证未登录桌面时应用和代理都能运行。任务失败需有告警，不能只依赖有限次数的自动重试。Windows 服务日志接入由 IT 按所用托管工具配置。

该模板不会自动注册任务、调整防火墙、改变系统电源设置或安装软件。

## Linux（systemd）

1. 示例程序目录 `/opt/product-image-library`，数据目录 `/srv/product-image-library/data`。建立专用 `assetlibrary` 用户及同名组，赋予程序读取、数据读写权限。
2. 在程序目录执行 `python3 -m venv .venv`，再执行 `.venv/bin/python -m pip install -r requirements.txt`。
3. 将 `linux.env.example` 编辑后保存到 `/etc/product-image-library.env`；将服务模板编辑后保存到 `/etc/systemd/system/product-image-library.service`。确保路径与实际安装一致。
4. IT 核对后执行 `systemctl daemon-reload` 和 `systemctl enable --now product-image-library`。Caddy 使用它的独立服务配置。
5. 使用 `systemctl status product-image-library` 和 `journalctl -u product-image-library` 查看运行状态与日志；配置日志保留和故障告警。安排一次重启验收。

Linux 服务模板尚未在目标 Linux 机器运行；当前开发机是 Windows。

## 定时备份与维护

使用 `manage.py backup` 定时备份，启动该命令的任务必须设置与应用相同的 `ASSET_DATA_DIR`。每次使用唯一的新目录名称，检查命令退出码和 `backup.json`。建议每日备份，并按公司要求保留周期副本；备份至少有一份独立于应用磁盘。

备份任务由 IT 按最终操作系统配置任务计划或 systemd timer；本文没有创建定时任务，也不会自动清理旧备份。定期做恢复演练，并监控数据盘、临时目录、日志盘空间、进程状态、证书有效期和备份结果。

## 员工与 AI 取图

管理员为员工创建内部账号；外部账号只读，但当前可查看全部正常图库。若未来要对不同客户隔离产品，需要另做授权范围功能。

员工电脑上的 MCP 工具保持本地运行，将 `ASSET_SERVER_URL` 改成正式 HTTPS 地址，`ASSET_EXPORT_DIR` 仍填员工本机目录，令牌通过客户端受控配置提供。VPN 必须先连通。若 Python 不信任公司 CA，可为 MCP 进程设置 `SSL_CERT_FILE` 为公司提供的 CA 证书包；保留 TLS 校验。

## 上线验收

- 内网电脑和 VPN 电脑分别能解析域名、打开 HTTPS 页面，证书有效。
- 未登录不能读取图片或数据库；代理入口不能初始化管理员。
- 管理员、内部账号、外部账号的权限符合现有规则；配置好的正式地址可复制分享。
- 能上传接近限制的大图、生成缩略图、下载原图和批量 ZIP；核对原图哈希与迁移前一致。
- 多台电脑分别尝试错误登录时限流互不串联，正确登录 Cookie 带 Secure 标记。
- 产品、分类、图片总数及现有用户数据与最终备份一致；回收站也能正常访问。
- 员工的真实 MCP 客户端能搜索并导出原图到自己的电脑。
- 服务器重启后恢复服务；完成一次独立备份恢复测试后交接给维护人。

## 配置参考

- [FastAPI：部署与进程管理](https://fastapi.tiangolo.com/deployment/concepts/)
- [FastAPI：反向代理与可信转发头](https://fastapi.tiangolo.com/advanced/behind-a-proxy/)
- [Caddy：反向代理](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
- [Caddy：使用自有 TLS 证书](https://caddyserver.com/docs/caddyfile/directives/tls)
- [Caddy：Windows / Linux 后台服务](https://caddyserver.com/docs/running)
- [Microsoft：任务失败重启与运行时限设置](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset?view=windowsserver2025-ps)
