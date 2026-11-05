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

## 连接到远端仓库

先在 GitLab / GitHub / Gitee 上建一个**空的**仓库（不要勾选初始化 README），然后：

```powershell
git remote add origin <你的仓库地址>
git push -u origin main
```

之后每次推送：

```powershell
git push
```

### 推送前请确认

- 代码里没有公司敏感信息（内部地址、产品未发布信息、客户数据）
- 推到公有平台（GitHub / Gitee 公开仓库）前，最好先建**私有仓库**

## 建议的提交习惯

- 一次提交只做一件事，提交信息写清楚「改了什么、为什么」
- 改动前先 `git status` 确认没有意外的文件被加进来
- 特别留意：不要把 `data/`、`.env` 加进仓库
