# Setup Guide

本仓库提供 Copilot 跨项目 brain、一个原生路由 skill 和 Windows 后台记忆整理器。
只启用通用方法；股票交易、跨境电商专属流程需要真实业务目标和验收标准，尚未内置。

## 本机入口

- `AGENTS.md`：常驻规则和 lazy-loading 边界。
- `rules/USER.md`：公开模板；本机配置在被 Git 忽略的 `rules/USER.local.md`。
- `rules/skills/INDEX.md`：参考工作流索引，命中后再读具体文件。
- `integrations/copilot/skills/personal-brain/SKILL.md`：唯一原生 brain skill。
- `contexts/memory/INBOX.md`：事务采集方法，不是可追加的数据文件。

## 新机器安装

```powershell
.\integrations\copilot\install.ps1 -WhatIf
.\integrations\copilot\install.ps1
copilot instruction list --json
copilot skill list --json
```

安装器将 skill 源目录注册到 Copilot，并在用户级 instructions 中维护一个带标记的
bootstrap；保留其他用户指令，不复制全套文档。仓库移动后重新安装并清理旧注册路径。
Git clone 本身不会安装全局入口或系统任务。

新会话自动发现入口；现有会话可 `/skills reload`。
跨仓库首次访问仍可能需要 `/add-dir <brain-root>` 或启动时
`copilot --add-dir <brain-root>`。不能把自动发现与授权访问混为一谈。
本机入口不会自动同步到其他机器、VS Code 扩展或 Copilot cloud agent。

## 后台记忆

从另一个仓库也可执行：

```powershell
python <brain-root>\tools\brain\memory.py status
```

采集由 Agent 在重要任务后主动调用 CLI；没有强制 session-end hook，不 dump 对话，
也不能保证每个会话都提交记录。仅接收非敏感的工程方法与工作流偏好。
实际数据、日志、审阅稿在 `.local`，不提交到 Git。

Windows 计划任务安装、运行身份和故障处理见 [自动记忆计划](docs/CRONTAB.md)：
每日 00:00 分类；周日 23:30 生成建议；只在用户确认后才改 rules。
Windows 保持登录时，锁屏或关闭聊天都不影响；注销/关机后不运行，恢复后尝试补跑。

Core 不需要 `.env` 或额外 API key；后台模型仍需要 Copilot 授权和可用网络。
语义搜索暂不启用，达到文档门槛只提示。

## 长任务与归档

长任务检查点保存在目标项目获准的本地目录，规范见
[长任务恢复](rules/skills/workflow_long_task_recovery.md)。这是可恢复性，不是保证永不丢上下文。

Apple/iOS、媒体、营销、邮件、发布及旧 OpenCode 代码已归档，不参与索引匹配。
外部 writing-skill 等迁移链接不等于安装完成；需要时确认依赖再安装。
恢复 archive 前修正移动后的相对路径、imports、平台与凭据配置。

## 本地验证

```powershell
python -m unittest discover -s tools\brain\tests -v
```
