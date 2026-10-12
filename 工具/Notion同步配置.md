# Notion 阅读页自动更新

每次推送到 `main`，GitHub Actions 检查正文，再把完整小说发布到固定的[Notion 阅读页](https://app.notion.com/p/584e0b9a371e82a2ba268108739458ab)。PR 只做校验。可在 Actions 中选择 **Sync manuscript to Notion → Run workflow**，以 `main` 手动重试。

本地 commit 需要 push 后才触发。一次 push 包含多个 commit 时发布最新稿；连续推送时排队发布，GitHub 可能合并尚未开始的任务。每次发布读取当时最新的 `main`，包含 Git 版本与提交时间；失败会在 Actions 中显示，不会作为同步成功。

## 一次性配置

1. 在 [Notion 连接管理](https://www.notion.so/profile/integrations)创建本工作区的内部连接，例如 `Manuscript GitHub Sync`，开启 **Read content** 和 **Update content**。无需评论或用户资料权限。
2. 在目标页面的菜单中，通过 **Connections / Add connections** 添加该连接；也可在连接管理的页面访问列表中授权该页。
3. 在 [GitHub Actions Secrets](https://github.com/chrisyao4700/raid-will-go-on/settings/secrets/actions)添加 repository secret：名称为 `NOTION_TOKEN`，值为该连接的 token。不要把 token 写进 Git、脚本、截图或聊天。
4. 将工作流合入 `main`。它会自动首次同步；若此前因为缺少 Secret 失败，完成配置后手动重跑。
5. 在 Notion 中确认阅读页对外分享状态；匿名读者需要页面已发布为网站或启用对应的公开分享。CI 只更新正文，不调整页面分享权限。

目标页面 ID 已配置在 [工作流](../.github/workflows/notion-sync.yml)中。将来换页时，修改 `NOTION_PAGE_ID`，并授权新页面。

## 阅读页约定

此页作为 Git 正文的发布副本，整页正文由 CI 管理；在 Notion 页内手写的文字会在下次同步时覆盖。阅读页链接保持不变。需要保留的反馈建议放在独立页面；正文替换可能影响挂在具体段落上的评论。

脚本仅从 `章节清单.json` 与 `正文/`合成全文，不读取或发布 `设定/`、`编辑记录/`、本地历史归档。Notion 默认的子页面及数据库删除保护保持开启：如果目标页中包含这些内容，同步会失败，需先将它们移到独立页面。

原文的 `* * *` 场景分隔符在发布时转换为 Notion 支持的 `---` 横线，避免被解析为三级空列表；Git 章节源文件保持原样。写入完成后检查 Notion 返回的完整正文，若出现空列表或正文被截断，则报告校验失败。

使用 Notion 官方 Markdown API（`2026-03-11`），无需第三方同步服务。完整正文一次提交，支持限流等待与异步任务轮询；只有收到成功写入结果后才通过。写入遇到超时或服务端错误时不自动重复提交，避免重复启动异步写入；请先检查 Notion 页面，再从 `main` 重跑。GitHub Actions 同时只运行一个同步工作流，且不取消正在写入的任务。

当前全文约 175 KB，单页约两千段落。脚本会提前检查 500 KB 的请求上限；如 Notion 拒绝更大的页面，需要改为章节子页面发布。轮询超时或任务被外部取消后，Notion 端任务可能仍在进行，应先确认完成状态再重跑。

## 本地校验

不需要 token，不访问 Notion：

```sh
python3 工具/合稿.py --check
python3 -m unittest discover -s 工具 -p 'test_*.py' -v
python3 工具/同步Notion.py --dry-run
```

预览位于忽略的 `.cache/notion-preview.md`。真实发布需要从安全环境注入 `NOTION_TOKEN` 和 `NOTION_PAGE_ID` 两个环境变量，然后运行 `python3 工具/同步Notion.py`；不要将凭证直接写入命令历史。

参考：[Notion Markdown 更新 API](https://developers.notion.com/reference/update-page-markdown)、[大文档异步写入](https://developers.notion.com/guides/data-apis/working-with-markdown-content#running-large-markdown-writes-asynchronously)。
