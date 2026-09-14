# AGENTS.md - Personal Brain Bootstrap

这个仓库是个人 brain/meta library。它提供跨项目的身份、沟通规则、决策公理、skills 和长期记忆，不替代目标项目自己的代码规范。

## 每次 Session

只加载以下常驻入口：

1. `rules/SOUL.md`
2. `rules/USER.md`，以及存在时的本机 `rules/USER.local.md`
3. `rules/COMMUNICATION.md`
4. `rules/WORKSPACE.md`
5. `rules/skills/INDEX.md`

这是常驻层。不要预加载全部 skills 或 axioms。

## Lazy Loading

- 任务命中 `rules/skills/INDEX.md` 中的触发场景后，再读取对应 skill。
- Copilot 原生入口是 `personal-brain` skill；索引中的 Markdown 是按需参考文件，
  不代表每个工具已安装或已授权。迁移到外部 repo 的链接不是本地实现。
- 所有参考文件中的工具名、平台命令、模型路由以当前运行时为准。不要调用旧 OpenCode
  agent 名、Unix-only 命令或不存在的工具；不因参考文件声称某模型零留存就外发数据。
- 战略、架构、验证、长期记忆或用户认知相关任务，先读 `rules/axioms/INDEX.md`，再按触发词读取相关 axiom。
- `archive/`、`rules/skills/archive/`、`tools/archive/` 和 `periodic_jobs/ai_heartbeat/archive/` 默认不搜索、不加载；只有用户明确要求恢复旧能力时才读取。
- 目标项目有自己的 `AGENTS.md` 或 `.github/copilot-instructions.md` 时，两者同时生效；目标项目规则负责代码与工程约束，本仓库负责跨项目偏好和方法论。

## 文件路由

先查 `rules/WORKSPACE.md`。目标项目的代码和文档仍写入目标项目；只有跨项目知识、记忆和 brain 资产写入本仓库。

## 长期记忆与任务恢复

- 采集前读 `contexts/memory/INBOX.md`，使用事务 CLI；不要追加或编辑生成的视图。
- 只记录明确非敏感的工作流偏好和已验证工程方法，不保存用户画像、身份、履历、
  财务、健康、关系、法律或其他敏感数据，也不保存源码、凭据和原始会话。
- 每日整理候选；每周只生成审阅建议，经用户确认后才应用到 rules。
- 新会话需要记忆或任务结束准备采集时运行 `tools/brain/memory.py status`，
  有失败、待审稿或语义搜索门槛提示时告知用户，不反复提醒相同的已知问题。
- 长任务/中断恢复先读 `rules/skills/workflow_long_task_recovery.md`；项目检查点留在
  目标项目获准的本地 artifact 目录，不把任务状态塞进中央长期记忆。

## Multi-Agent

大型、可并行、调研重或需要独立交叉验证的任务，先读 `rules/skills/workflow_parallel_subagents.md`。单点任务不要为了并行而并行。

## Safety

- 不外泄私人数据。
- 不执行未经确认的破坏性或外发操作。
- 技术执行自主推进；真正影响产品方向、成本、隐私或不可逆结果的决定才询问用户。
