# Douyin profile downloader recovery kit

用于 Windows PowerShell 7 的抖音作者主页批量归档方案。目标是：**作者发布作品全量/增量抓取 + 视频 + 原封面 + JSON 元数据**，并把安装、环境和浏览器翻页修复固定下来，避免以后重复排错。

> 这是个人归档/数据管理工具。只保存你有权访问和保存的内容，并遵守平台规则、版权和隐私要求。

## 当前已验证的关键点

2026-09-23 实际排查中，抖音普通 CLI 主页接口会返回 `403 ArgusSecurityPlugin Uifid Not Found`，但网页内部请求可以继续获得主页分页。最终 v2.3 兼容 `www.douyin.com` 与 `www-hj.douyin.com` 的 `/aweme/v1/web/aweme/post/` 响应，并修复了浏览器滚动过程中反复滚回旧位置的问题。

在当次目标账号测试中，网页分页最终收集到 **307** 条作品，末页返回 `has_more=0`；本地随后确认 **307 个非空 MP4 + 307 张非空封面**。这只是当时该账号和网页会话的实测结果，不保证未来平台接口不变化。

## 最快恢复

在 PowerShell 7：

```powershell
git clone https://github.com/wtyliangtingRe/douyindownload.git
Set-Location .\douyindownload
.\setup.ps1 -RunAfterInstall
```

默认参数就是本次使用的配置：

- 作者主页：`https://www.douyin.com/user/MS4wLjABAAAAFu86FkpJPIXePsIHnQ2dQgf8eJ9ZIOryBZhoHwU0tOQ`
- 保存目录：`E:\0\laobaiSave`

要改作者或目录：

```powershell
.\setup.ps1 `
  -ProfileUrl 'https://www.douyin.com/user/你的sec_uid' `
  -OutputRoot 'E:\0\anotherSave' `
  -RunAfterInstall
```

首次运行/登录失效时，浏览器可能要求登录或验证码。**只在自动打开的浏览器里完成登录/验证；不要把 Cookie、YAML 配置或 browser-state 文件提交到 GitHub。**

## 以后继续增量下载

```powershell
.\run.ps1
```

或直接：

```powershell
& 'E:\0\laobaiSave\_tool\.venv\Scripts\python.exe' `
  'E:\0\laobaiSave\_tool\laobai-browser-v23.py'
```

已存在的主媒体会被增量逻辑跳过；缺失的主文件允许重新补下。

## 本地配对检查

```powershell
.\check.ps1
```

它检查：

- 非空 MP4 数量
- 非空 `_cover.jpg` 数量
- 空视频
- 每个视频是否缺对应封面

这只是本地文件存在性/大小与配对检查，不等于逐个播放验证，也不单独证明账号历史内容绝对完整。

## 文件结构

```text
douyindownload/
├─ setup.ps1                   # 一键恢复环境与配置
├─ run.ps1                     # 以后继续/增量下载
├─ check.ps1                   # 本地视频/封面配对检查
├─ src/
│  └─ browser_runner_v23.py    # 最终浏览器分页兼容入口
├─ THIRD_PARTY_NOTICES.md
└─ .gitignore                  # 明确排除 Cookie、登录状态、媒体、日志、数据库
```

运行后本地（默认）会出现：

```text
E:\0\laobaiSave\
├─ media\
└─ _tool\
   ├─ .venv\
   ├─ browsers\
   ├─ douyin-downloader-<pinned commit>\
   ├─ download-laobai.py
   └─ laobai-browser-v23.py
```

## 为什么锁定上游版本

`setup.ps1` 固定使用 `jiji262/douyin-downloader` 的提交：

```text
f7ec48f9cfe1fc80b0093440c62c0c60425c31b2
```

这样以后误删本地环境时，恢复的是**这次已经排查过的组合**，避免上游代码变化后旧补丁错位。平台本身仍可能变化，所以若未来再次失效，应优先保留日志和 `browser-diagnostic-v23.json` 做新一轮适配，而不是删除已下载媒体。

## v2.3 这次解决了什么

1. 原 CLI API 被 Argus/Uifid 校验拒绝后，改用 Playwright 浏览器读取网页真实分页响应。
2. 浏览器响应监听提升到 context 级，避免页面切换时丢响应。
3. 修复滚动逻辑把页面反复拉回“最后一个已识别作品”的问题。
4. 接收两个实测会承载作者作品分页的域名：
   - `www.douyin.com`
   - `www-hj.douyin.com`
5. 保留严格的 `sec_user_id` / 作者检查，避免把其他作者内容混入。
6. 页面返回 `has_more=0` 时记录 `web_reported_end`，并生成诊断 JSON。
7. 增量下载已有作品，不要求删除数据库或重下旧文件。

## 安全注意

`.gitignore` 已排除常见敏感和大文件，但仍建议提交前执行：

```powershell
git status --short
```

尤其不要提交：

- `cookies.json`
- `*browser-state*.json`
- `laobai*.yml`
- `*.db`
- `media/`
- `_tool/`
- 下载日志和诊断文件（除非人工脱敏后明确要保存）

## 上游与许可

本仓库不是 `jiji262/douyin-downloader` 的替代品，而是一个锁定版本的恢复/兼容包装层。第三方许可说明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
