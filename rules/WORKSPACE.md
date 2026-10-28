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

## 源码、敏感配置与云盘产物

OneDrive 仅存放获准同步的非敏感产出文件，不放源码、凭据或敏感配置。源码及持续维护的第三方改动放在目标项目的 Git 仓库或可追踪的子模块中，不能仅因放入 `.local` 等忽略目录而丢失版本管理。密钥与敏感配置仅本地保存，不提交 Git，不同步云盘。云盘适用范围不等于允许自动上传：新增同步路径、搬移或删除既有文件仍须核对项目权限与数据范围。

## Inactive

- 暂不使用的 skills：`rules/skills/archive/`
- 暂不使用的外部集成：`tools/archive/`
- 旧 OpenCode heartbeat 与外部定时任务：`periodic_jobs/ai_heartbeat/archive/`

Inactive 内容不参与默认搜索和 lazy loading。

## 多机 Git 同步

同一仓库可能由不同机器或会话共同维护。开始工作、发现本地分支落后，以及每次 push（含失败重试）之前，均先 `git fetch origin` 并核对当前分支与上游差异；默认继续使用现有分支，不因落后而新建分支。`fetch` 只更新远端引用，不等于工作树已同步；发现落后时应继续完成更新，不能只反复报告落后。能够快进时使用 `git merge --ff-only`；若重叠文件有未提交修改，先在获准的本机私有目录备份原文、基线及补丁，再快进并以三方合并恢复本地改动。分支已有双方提交时，在当前分支正常 merge，保留双方历史。可确定的文本冲突自主协调并验证，只有语义取舍不明或涉及权限/产品决策时才说明具体问题请用户决定。不得强推、自动变基、丢弃本地修改或把他人的工作夹带进新提交。提交和推送只包含本次获准、核验可公开的产物；私有历史引用与 `.local` 记忆不上传。

包含子模块时，分别核对主仓库与本次相关子模块的当前分支、上游和所需提交；
主仓库已更新不代表子模块已同步。先检查子模块本地修改及主仓库记录的指针，
不以更新为由丢弃修改或擅自切换全部子模块到远端最新版本。
明确区分跟随主仓库固定提交与获准合并子模块分支，完成后验证两层状态。

## 整理验收与发布授权

本仓库的非敏感知识整理产物已获用户持续授权：完成隐私审查、证据核对、适用性判断与必要验证后，直接在现有分支提交并推送，不逐次询问是否发布。该授权仅限本仓库可公开的整理文档、方法及相关配置；不包含原始对话、私有引用、个人资料、凭据、扩大数据来源或修改安全边界。冲突、权限不足、敏感性不确定或实质性新决策仍应明确报告，不强行发布。

统一设置必须分别验收并报告上下文入口安装、获准历史来源接入、知识提炼实际结果；前一项成功不代表后一项完成。来源缺失或格式不支持须明确说明，不宣称覆盖所有助手。日整理与周整理在同一维护任务内串行，周日先日后周；若上周应执行的综合整理缺少成功或正常跳过记录，下次维护应补跑，不以调度器的触发时间戳代替任务完成记录。

每次维护必须检查遗留提案，不只处理本轮新生成的草稿。逐项比较既有规则后，记录实际落地文件、与现有规则等效的合并依据，或缺少证据/需要决策的具体阻塞。草稿生成不等于整理完成；仅在实际应用后标记 applied，确认无需新增时才以明确依据 dismissed。不能将另一终端的总结冒充本机已生成或已验证的成果；本机私有队列不随 Git 自动同步。

## 命名

- 目录和文件名使用小写 snake_case。
- 临时一次性项目使用 `tmp_<name>/`。
- 根目录 `.venv/` 是工作区级 Python 环境；需要隔离时在项目目录内创建独立环境。
