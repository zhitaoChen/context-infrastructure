# Context Infrastructure — Reference Implementation

> English version: [https://github.com/grapeot/context-infrastructure-en](https://github.com/grapeot/context-infrastructure-en)
>
> 背景阅读：[为什么AI只会说正确的废话，以及怎么把它逼出舒适区](https://yage.ai/context-infrastructure.html)

这是基于原作者 reference implementation 改造的个人 brain 仓库：
提供跨项目规则、按需工作流、事务化记忆采集和后台整理；当前本机使用 Pi，
Copilot 安装入口与旧后台方案仍保留。

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

## 从使用到知识沉淀

1. **接入上下文**：工具的全局入口定位本仓库，读取 `AGENTS.md` 与常驻规则。
2. **按需使用**：根据索引加载相关 skill／公理，实际工程产物仍留在目标项目。
3. **采集经验**：从主动提交或已授权的本机历史中提炼非敏感方法；对话不是规则，
   助手自述不是成功证据，私有原文与本机配置不进入 Git。
4. **每日筛选**：分类候选，接受或拒绝；接受表示值得后续综合，不等于写入正式规则。
5. **每周综合**：比较不同来源，生成带证据与适用边界的私有审阅提案，不为凑数量新增公理。
6. **审阅归位**：有上下文的维护会话检查新旧提案，对照现有知识；方法补充到 skill，
   有充分依据的判断原则进入公理，尚不适合晋升的内容保留本机知识与证据。
   重复内容合并，证据不足保留待审，工具专属细节不强塞进通用规则。
7. **验证与同步**：确认实际文件修改与索引后记录审阅结果，按授权 commit/push。
   私有整理成功、正式知识生效和远端同步是三个独立验收点。

终点是知识库得到可复用的改进，不是每天增加一份总结报告。后台受限模型只负责
采集、筛选和提案；不能将草稿已生成或 Git 无改动当作审阅落地已完成。
运行方式、任务时间与机器边界见 [CRONTAB.md](docs/CRONTAB.md)。

## 三层结构

**展示层（可以参考，不能复制）**：[`rules/axioms/`](rules/axioms/) 和 [`rules/skills/`](rules/skills/) 包含了这个系统积累一年的内容。43 条公理是从具体经历中蒸馏出来的，skills 是从真实项目中总结的。这些代表原作者的视角，对你有参考价值，但不能替代你自己积累的认知。

**当前 active 层**：[`rules/SOUL.md`](rules/SOUL.md)、[`rules/USER.md`](rules/USER.md)、
[`rules/COMMUNICATION.md`](rules/COMMUNICATION.md) 和两个索引组成常驻入口。具体 skills
与 axioms 按任务 lazy load。当前 Pi 后台由 Windows Task Scheduler 执行日常提炼与周度提案；
正式知识经审阅归位后生效，不自动生成公开日报，配置见
[`docs/CRONTAB.md`](docs/CRONTAB.md)；不相关能力保存在 archive，不参与默认加载。

**不可复用层**：公理的具体内容、skill 背后的具体经验。理解它们的结构和形成方式，然后从你自己的数据中积累。

---

## License

MIT
