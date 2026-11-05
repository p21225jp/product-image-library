# 版本控制说明

本仓库用 Git 管理源码。**运行时数据不纳入版本控制。**

## 仓库现状

- 分支：`main`
- 首次提交：`fc72061` 初始提交：内网产品图片库
- 纳入版本控制：42 个文件（代码、静态资源、文档、测试、部署示例）

## 什么被排除在外

| 路径 | 原因 |
| --- | --- |
| `data/` | 真实素材（原图、缩略图）和 SQLite 数据库，含管理员密码哈希与令牌哈希 |
| `.venv/` | Python 虚拟环境，可由 `requirements.txt` 重建 |
| `exports/` | 取图工具导出的图片 |
| `.env` | 环境变量，可能含密钥 |
| `__pycache__/`、`.pytest_cache/` | 构建缓存 |

如果要备份 `data/`，用项目自带的一致性备份命令，不要用 Git：

```powershell
.\.venv\Scripts\python.exe manage.py backup 'D:\AssetBackups\2026-11-05'
```

## 日常操作

```powershell
# 查看改了什么
git status
git diff

# 提交改动
git add -A
git commit -m "说明这次改了什么"

# 查看历史
git log --oneline

# 回滚某个文件到上次提交
git checkout -- app/main.py
```

## 提交与推送规则

分成两类，区别对待。

### 轻微改动：可以自动提交并推送

以下改动完成后，直接 `git add` + `git commit` + `git push`，不用等确认：

- **文档**：`README.md`、`GIT.md` 等 markdown，文案错别字。
- **样式**：CSS 颜色、间距、字号等不影响功能的视觉微调。
- **单行 bug 修复**：改动小、风险可控、不影响接口或数据结构的代码修补。

### 重要改动：等明确要求再提交和推送

功能开发、重构、改多个文件、动数据库结构、改接口——完成后**只把文件留在工作区**，报告改了什么，等本人发话再提交推送。

**当你要提交时：**

```powershell
git add -A
git commit -m "说明这次改了什么"
```

**当你要推送时：**

```powershell
git log --oneline origin/main..HEAD   # 先看会推送哪些提交
git push
```

## 重要改动前的检查

**动手做功能开发、重构或涉及多个文件的改动之前，先确认工作区是干净的。**

```powershell
git status --short
```

- 输出为空 → 工作区干净，可以开始。
- 有输出 → **停下来报告，由本人决定**是提交、丢弃还是继续，不擅自处理已有改动。

这样万一改动方向不对，可以随时 `git checkout -- .` 回到上一个完整状态，不会和之前未完成的改动混在一起。

纯文档、单行文案这类微调不必检查。

## 远端仓库

已配置：

```
origin  https://github.com/p21225jp/product-image-library.git
```

首次推送（需要 GitHub 认证）：

```powershell
cd "H:\AI本地文档\开发\product-image-library"
git push -u origin main
```

认证方式二选一：

1. **浏览器弹窗登录**：如果 Git 配置了 Credential Manager，会弹出 GitHub 登录窗口，登录即可。
2. **用个人访问令牌（PAT）**：在 GitHub「Settings → Developer settings → Personal access tokens」生成，
   权限选 `Contents: Read and write`。推送时用户名填 GitHub 用户名，密码位置粘贴令牌。

之后每次推送：

```powershell
git push
```

## 提交前自检

推送前建议确认没有把内部信息带出去：

```powershell
# 确认 data/ 没被跟踪
git ls-files | Select-String "^data/"

# 提交前看一眼将要推上去的内容
git log --oneline origin/main..HEAD
```

### 推送前请确认

- 代码里没有公司敏感信息（内部地址、产品未发布信息、客户数据）
- 推到公有平台（GitHub / Gitee 公开仓库）前，最好先建**私有仓库**

## 建议的提交习惯

- 一次提交只做一件事，提交信息写清楚「改了什么、为什么」
- 改动前先 `git status` 确认没有意外的文件被加进来
- 特别留意：不要把 `data/`、`.env` 加进仓库
