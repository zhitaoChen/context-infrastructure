# Context Infrastructure — Reference Implementation

> English version: [https://github.com/grapeot/context-infrastructure-en](https://github.com/grapeot/context-infrastructure-en)
>
> 背景阅读：[为什么AI只会说正确的废话，以及怎么把它逼出舒适区](https://yage.ai/context-infrastructure.html)

这是基于原作者 reference implementation 改造的个人 brain 仓库：
为 Copilot 提供跨项目规则、按需工作流、事务化记忆采集和 Windows 后台整理。

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

## 目录结构

```
context-infrastructure/
├── AGENTS.md                    # 根路由表（AI 每次 session 的起点）
├── setup_guide.md               # 配置指引
├── .env.example                 # 环境变量模板
│
├── docs/
│   ├── CRONTAB.md               # Copilot 自动记忆计划
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
│       ├── install.ps1          # Windows 计划任务安装器
│       ├── run.ps1              # 非交互执行入口
│       ├── prompts/             # Copilot observer / reflector
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
与 axioms 按任务 lazy load。自动记忆由 Windows Task Scheduler 启动受限 Copilot，
每周只输出人工审阅提案，配置见
[`docs/CRONTAB.md`](docs/CRONTAB.md)；不相关能力保存在 archive，不参与默认加载。

**不可复用层**：公理的具体内容、skill 背后的具体经验。理解它们的结构和形成方式，然后从你自己的数据中积累。

---

## License

MIT
