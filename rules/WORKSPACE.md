# WORKSPACE.md - Brain 目录路由

本文件只路由 `context-infrastructure` 中的跨项目资产。处理其他仓库时，代码、测试和项目文档留在目标仓库，不要搬到这里。

## Active

- 常驻身份与沟通：`rules/SOUL.md`、`rules/USER.md`、`rules/COMMUNICATION.md`
- 本机用户配置：`rules/USER.local.md`（可选，Git 忽略，不是长期记忆输入）
- Skill 路由：`rules/skills/INDEX.md`
- 决策公理路由：`rules/axioms/INDEX.md`
- 采集与检索入口：`contexts/memory/INBOX.md`、`contexts/memory/OBSERVATIONS.md`
- 实际记忆、视图、审阅稿、日志：`contexts/memory/.local/`（Git 忽略）
- 调研报告：`contexts/survey_sessions/`
- 思考、复盘、方法论：`contexts/thought_review/`
- 每日日志：`contexts/daily_records/`
- AI 会话归档：`contexts/ai_sessions/<source>/`
- 定时记忆任务：`periodic_jobs/ai_heartbeat/`
- 通用工具：`tools/`
- 事务记忆 CLI 与测试：`tools/brain/`
- Copilot 原生 skill：`integrations/copilot/skills/personal-brain/SKILL.md`
- 长任务恢复约定：`rules/skills/workflow_long_task_recovery.md`（检查点留在目标项目）
- 一次性跨项目实验：`adhoc_jobs/<project>/`

## Inactive

- 暂不使用的 skills：`rules/skills/archive/`
- 暂不使用的外部集成：`tools/archive/`
- 旧 OpenCode heartbeat 与外部定时任务：`periodic_jobs/ai_heartbeat/archive/`

Inactive 内容不参与默认搜索和 lazy loading。

## 命名

- 目录和文件名使用小写 snake_case。
- 临时一次性项目使用 `tmp_<name>/`。
- 根目录 `.venv/` 是工作区级 Python 环境；需要隔离时在项目目录内创建独立环境。
