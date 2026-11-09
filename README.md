# MKT团队素材空间 · 云端版

源项目：[p21225jp/product-image-library](https://github.com/p21225jp/product-image-library)，提交 `9f94c29c100a7b2348f33165b792dd43d06d28a4`。保留原作者与 AGPL-3.0-or-later 许可，GitHub 原仓库和本地应用未修改。

## 云端运行

界面沿用原系统。后端适配 Sites / Cloudflare Workers，D1 保存产品、分类、账号、会话、令牌哈希和记录，私有 R2 保存原图与缩略图。真实素材和凭据不进入源码仓库。

站点默认仅所有者可访问。先通过 ChatGPT 站点身份验证，再用原素材库管理员账号密码登录；密码哈希可原样迁移，无需重置。图库内创建的账号仍受 Sites 访问范围限制：给同事使用时需同时授予 Sites 访客权限。外部账号目前可查看整个正常图库，没有按产品隔离。

保留 SKU 精确搜索与前导零、名称/别名/文件名/标签包含查询、分页、分类管理、图片批量关联、上传、下载、回收站、账号和令牌管理。没有新增图片语义识别或云端模型调用。

上传时由浏览器解码原图、识别透明像素并生成最长边 720 的 WebP 预览，原图字节原样上传。服务端校验文件容器、格式、像素上限与缩略图尺寸，并计算原图 SHA-256；透明像素判定来自浏览器，不使用服务器 Pillow 完整解码。支持静态 JPG/PNG/WebP，单张 25 MB / 4000 万像素，前台每批 30 张。直接调用上传 API 需额外提供 thumbnail、display_width、display_height、has_alpha 表单字段。

ZIP 流式返回，最多 100 张 / 500 MB，不把整包放入 Worker 内存。永久删除先写持久队列再清理文件，失败任务在后续永久删除或查看操作记录时重试。

## AI 取图

mcp_bridge.py 保留原 stdio MCP 工具，新增可选 ASSET_SITES_TOKEN。私有 Sites 的服务访问令牌和图库 API 令牌是两层独立凭据。

- ASSET_SERVER_URL：站点的 HTTPS 地址。
- ASSET_API_TOKEN：网页 AI 取图页面创建的图库令牌。
- ASSET_WRITE_API_TOKEN：管理员签发、scope 为 `products:create` 的独立写入令牌；只取图时可不配置。
- ASSET_SITES_TOKEN：Sites 站点服务访问令牌。
- ASSET_EXPORT_DIR：智能体所在电脑的素材输出目录。

服务访问令牌置于 OAI-Sites-Authorization 请求头，图库令牌置于 Authorization 请求头。不要将凭据写入源码或 URL。取图工具把原图下载到本机，只向模型返回文字，不必将站点改为公开。

MCP `create_product(sku, name, category='', aliases=[])` 新建产品，SKU 为字符串并保留前导零。分类为已有的单个分类；空值表示未分类。SKU 冲突返回 409，不覆盖资料。写入工具只使用 ASSET_WRITE_API_TOKEN，不回退到取图令牌。此授权不允许修改或删除产品、创建分类、修改图片及管理账号。所有创建记录关联令牌 ID，可在操作记录追踪；撤销令牌立即失效。结构迁移为旧令牌保留 `read` 权限，不自动提升权限。

管理员可在 AI 取图页选择“查询、下载和新建产品”签发令牌，也可运行 `tools/authorize_mcp_admin.py`：脚本从本机 Codex 配置读取站点地址和平台认证，在本机窗口输入管理员账号密码，签发专用令牌并写入该 MCP 的私有配置，随后退出临时管理员会话。管理员密码不保存；凭据不作为命令行参数、日志或返回给模型。该脚本不会创建任何产品。

## 开发与验证

保留 Sites/Vinext 的初始化与构建集成。配置见 .openai/hosting.json。结构迁移由 npm run db:generate 生成，禁止在请求内建表或改表。

运行 node scripts/test-library.mjs、node node_modules/typescript/bin/tsc --noEmit，使用 npm run dev 预览，npm run build 构建。本地数据库与云端隔离。

图片详情窗口点击后立即打开，先展示当前列表已有资料，再并行核对图片详情与加载产品候选；核对完成前不能保存，失败可重试。关闭或切换图片会忽略旧请求。产品候选在当前页面内缓存 60 秒、最多 25 个搜索条件，共享相同的进行中请求；产品新建、修改、删除、手动刷新和退出登录时清除缓存。窗口不会等待原图下载。

`node scripts/test-detail-loading.mjs` 覆盖立即弹窗、并行加载、缓存复用与失效、晚到请求隔离、失败重试以及只读权限。

测试覆盖鉴权、撤销、角色隔离、SKU 前导零、别名、分类变更、关联冲突、回收站、原图字节一致性、流式 ZIP 和迁移关闭。

## 数据迁移

先用原项目 manage.py backup 生成一致性备份。通过临时迁移密钥与 Sites 服务访问身份导入记录和文件；真实数据不放进 SQL 结构迁移或源码。保留原 ID，原图与预览逐个核对 SHA-256；迁移完成核对数量并关闭入口。最终发布版本移除迁移接口。

迁移为快照复制，后续云端和本地不会自动同步。原目录完整保留。
