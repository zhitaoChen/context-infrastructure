# Context Infrastructure — Reference Implementation

> English version: [https://github.com/grapeot/context-infrastructure-en](https://github.com/grapeot/context-infrastructure-en)
>
> 背景阅读：[为什么AI只会说正确的废话，以及怎么把它逼出舒适区](https://yage.ai/context-infrastructure.html)

这是基于原作者 reference implementation 改造的个人 brain 仓库：
为 pi、Copilot 等已接入助手提供跨项目规则、按需工作流、事务化记忆采集，以及可审查、可发布的知识沉淀。调度可以使用 pi 会话内维护或单独安装的 Windows 后台执行器，两者不是同一个运行机制。

**核心定位**：这不是开箱即用的工具，而是一个可以参考的蓝图。Clone 下来后，你可以立刻体验「有 context vs 没有 context」的差异。但要让 AI 真正变成你自己的，需要从头采集你的行为数据——没有捷径。

---

## Quick Start（5 分钟）

```powershell
git clone https://github.com/zhitaoChen/context-infrastructure
Set-Location context-infrastructure
.\integrations\copilot\install.ps1
```

公开用户模板是 [`rules/USER.md`](rules/USER.md)，个人配置留在被 Git 忽略的 `rules/USER.local.md`。
Copilot CLI 通过用户级
`~/.copilot/copilot-instructions.md` 自动定位本仓库，再按 [`AGENTS.md`](AGENTS.md)
执行 lazy loading。

详细步骤见 [`setup_guide.md`](setup_guide.md)。

如果你想把它扩展成更完整的工作系统，可以看 [`docs/SKILL_ECOSYSTEM.md`](docs/SKILL_ECOSYSTEM.md)。那里列了一组可单独安装的 public skill repo，例如 Web 搜索、Google Docs、Google Maps、邮件/newsletter、OpenCode、PPTX、社交媒体、支付分析、家庭网络分析和本地 process launcher。`context-infrastructure` 保持轻量；完整能力通过独立 repo 按需安装。

---

## 实际工作闭环：每一步做什么

1. **接入并加载上下文**：安装用户级指令入口，每次会话先读 `AGENTS.md` 与常驻规则；按当前任务读取相关 skills/axioms。参考库不是用户个人经历，也不是已验证的新知识。
2. **完成实际任务**：在目标项目中执行、验证并保留产物。仅有助手声称成功，不算方法已经验证。
3. **采集获准证据**：Agent 通过 `memory.py capture` 提交安全抽象，或在明确授权的来源与时间范围内采集历史引用。引用只是指针，不是知识；历史配置、原文与凭据不随 Git 同步。
4. **每日提炼与分类**：由当前执行器审阅获准输入，排除一次性任务、自动提示、敏感和无依据内容，将长期方法或明确工作流偏好写入事务队列；daily 再接受或拒绝候选。不得为了每天有产物而凑数。
5. **每周综合与落地**：比较已接受观察和既有规则；重复的合并，工具细节留在工具层，证据不足的不升级为通用方法。逐项留下实际规则文件、等效覆盖依据或具体阻塞，不能停在草稿阶段。
6. **验证并同步公开知识**：本仓库已有持续发布授权的非敏感整理产物，验证后直接 commit/push；每次 push（含重试）前 fetch 并核对远端，沿用现有分支，安全可快进时更新。敏感、权限扩大或新的实质性决策仍需明确确认。没有公开变更不创建空提交。

**完成标准是经验进入可复用文档并实际发布，而不只是定时器触发、引用入队或生成草稿；不为每天有提交而制造日报。** 私有证据留在 `.local`；经过隐私审查的公开摘要可以进入 `docs/knowledge/`，正式方法进入 `rules/skills/` 或相关文档，不能混为同一状态。

### 调度与多机边界

当前 pi 会话内维护默认每天北京时间 **23:00**，周日在同一任务中先日整理、再周整理；缺少周执行记录时补跑。规约见 [`pi_maintenance.md`](periodic_jobs/ai_heartbeat/prompts/pi_maintenance.md)。它需要 pi 保持运行，不代表机器关机后仍能执行。

Windows 后台执行器是另一种可选部署，必须单独安装、授权并核验计划任务，见 [`docs/CRONTAB.md`](docs/CRONTAB.md)。不要因仓库含有脚本便声称本机已安装；也不要同时开启两套调度而重复处理。

每台机器分别安装上下文入口、配置本机历史范围与运行器。Git 同步公开规则和脚本，不同步原始历史、认证、私有数据库或本机任务注册状态。运行健康用 `python tools/brain/memory.py status` 和实际调度器检查，不能只看 Git Log 推断任务成功。

## 目录结构

```
context-infrastructure/
├── AGENTS.md                    # 根路由表（AI 每次 session 的起点）
├── setup_guide.md               # 配置指引
├── .env.example                 # 环境变量模板
│
├── docs/
│   ├── CRONTAB.md               # pi / Copilot 可选后台记忆计划
│   └── SKILL_ECOSYSTEM.md       # 可单独安装的 public skill repo 目录
│
├── rules/
│   ├── SOUL.md                  # AI 的身份和行为基调（模板）
│   ├── USER.md                  # 你的偏好和背景（模板）
│   ├── COMMUNICATION.md         # 沟通风格指南（可直接用）
│   ├── WORKSPACE.md             # 目录路由索引
│   ├── axioms/                  # 43 条决策公理（展示层）
│   └── skills/                  # 25+ 个可复用 skill（展示层）
│
├── contexts/
│   ├── memory/
│   │   ├── INBOX.md             # 采集规范入口
│   │   ├── OBSERVATIONS.md      # 检索规范入口
│   │   └── .local/              # 本机数据库、视图、日志、审阅稿（Git 忽略）
│   ├── survey_sessions/         # 调研报告存放目录
│   ├── daily_records/           # 日常记录存放目录
│   └── thought_review/          # 思考复盘存放目录
│
├── periodic_jobs/
│   └── ai_heartbeat/
│       ├── install.ps1          # 可选 Copilot Windows 任务安装器
│       ├── install_pi.ps1       # 可选 pi Windows 任务安装器
│       ├── run.ps1              # Copilot 非交互执行入口
│       ├── prompts/             # 分类、综合、发布及会话维护规约
│       ├── docs/                # 记忆系统设计与 SOP
│       └── archive/             # OpenCode legacy 与外部 jobs
│
├── tools/
│   ├── brain/                   # 事务记忆 CLI 和测试
│   └── archive/                  # 未启用的外部集成
│
├── integrations/copilot/        # 原生 skill 与全局入口安装器
└── adhoc_jobs/                  # 按需任务存放目录
```

> 当前采用目录索引与关键词检索，不再保留旧 embedding 后端。
> 如后续需要语义搜索，再单独确认数据范围、服务与成本；它不是现有记忆流水线的依赖。

---

## 三层结构

**展示层（可以参考，不能复制）**：[`rules/axioms/`](rules/axioms/) 和 [`rules/skills/`](rules/skills/) 包含了这个系统积累一年的内容。43 条公理是从具体经历中蒸馏出来的，skills 是从真实项目中总结的。这些代表原作者的视角，对你有参考价值，但不能替代你自己积累的认知。

**当前 active 层**：[`rules/SOUL.md`](rules/SOUL.md)、[`rules/USER.md`](rules/USER.md)、
[`rules/COMMUNICATION.md`](rules/COMMUNICATION.md) 和两个索引组成常驻入口。具体 skills
与 axioms 按任务 lazy load。运行器、历史授权和公开发布是独立配置：pi 会话内维护使用当前模型；可选 Windows 后台运行器另行配置。自动生成的观察与草稿仍是待核验数据，经过有上下文的比较和隐私审查后，才合并为正式方法并按现有授权发布。不相关能力保存在 archive，不参与默认加载。

**不可复用层**：公理的具体内容、skill 背后的具体经验。理解它们的结构和形成方式，然后从你自己的数据中积累。

---

## License

MIT
