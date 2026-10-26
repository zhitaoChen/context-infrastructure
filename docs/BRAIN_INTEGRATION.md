# 多 Agent 共享入口

用户级入口使本机 Copilot、Claude Code、Codex、Gemini CLI 和 Pi 在各 Repo 引用中央 brain，
不需要向各项目复制全套规则、会话或数据库。项目规范继续生效。

```powershell
python tools/brain/bootstrap.py
python tools/brain/bootstrap.py --apply
```

默认预览；安装保留原指令与首次备份，重复执行不漂移。
Pi/Codex 已有同层 override 时更新 override。自定义 home、禁用全局指令、
其他设备、云端和 IDE 扩展需单独验证，不能声称所有运行时都已加载。

历史流程与发布契约见 [CRONTAB.md](CRONTAB.md) 和 `rules/WORKSPACE.md`。
Git 历史已有 Pi 采集、局部脱敏、串行日周维护与安全知识提交推送；
维护前必须同步远端，不能仅凭旧工作树重建已存在的方案。
私有队列留在 `.local`，审阅通过的通用方法归入正式 skills/axioms 后提交推送，
不能用私有摘要或按日公开报告代替知识落地。
