# Skills Index

只加载索引；命中任务后再读取对应文件。一个任务可以组合少量相关方法，
不因某项列在这里就认为其 CLI、账号或外部服务已安装。

**原生入口**：`personal-brain`，源码在 `integrations/copilot/skills/personal-brain/SKILL.md`。
本页的普通 Markdown 是参考工作流，不是各自独立的原生 skill。
工具参数、权限、平台命令与模型选择一律以当前运行时为准。

## 工程与 Agent

| 场景 | 参考文件 |
|---|---|
| 长任务、context 丢失、中断恢复、检查点 | [长任务恢复](./workflow_long_task_recovery.md) |
| 可独立拆分的大任务、并行子 Agent | [并行工作流](./workflow_parallel_subagents.md) |
| 后台任务停滞、失败诊断 | [Watchdog](./workflow_watchdog.md) |
| 延时执行、关闭 CLI 后仍需运行 | [调度边界](./delayed_execution.md) |
| AI 编程的需求、成功标准、验证 | [编程方法论](./bestpractice_ai_programming_mindset.md) |
| 调试失败、验证假设 | [调试诊断](./bestpractice_ai_debugging_diagnosis.md) |
| 项目脚手架与重整 | [脚手架](./project_scaffold.md) |
| 风险隔离、分阶段处理 | [分阶段工作法](./bestpractice_staged_approach.md) |
| GUI 自动化 | [GUI 方法论](./bestpractice_gui_automation.md) |
| 浏览器 fetch/XHR 协议调试 | [Ajax Capture](./playwright_ajax_capture.md) |
| 新建或改写 skill | [Skill 写作指南](./bestpractice_skill_writing.md) |
| AI 产品/技术选型 | [产品设计](./bestpractice_ai_product_design.md)、[决策逆向分析](./bestpractice_product_decision_analysis.md) |

## 调研与资料

| 场景 | 参考文件 |
|---|---|
| 深度调研、交叉验证来源 | [深度调研](./workflow_deep_research_survey.md) |
| 股票 consensus net income、盈利预期口径核验 | [共识净利润审计](./workflow_public_consensus_net_income_audit.md) |
| 论文分析、研究解读 | [论文调研写作](./workflow_research_paper_survey_writing.md) |
| arXiv 下载和格式转换 | [论文转换](./bestpractice_academic_paper_conversion.md) |
| 最新政策/数字/事实时效性 | [时间敏感信息验证](./bestpractice_temporal_info_verification.md) |
| Markdown 转 HTML | [HTML 转换](./bestpractice_markdown_html_conversion.md) |
| 内部文档版式 | [内部视觉规范](./bestpractice_internal_visuals.md) |
| 经验沉淀、知识迭代 | [知识飞轮](./workflow_knowledge_flywheel.md) |
| 面试方法论（不自动存储候选人画像） | [面试框架](./bestpractice_interview_evaluation.md) |

中文/国际搜索优先使用当前环境已安装的相应原生搜索 skill；不要复制配置已有能力。
股票交易和跨境电商专属流程尚未建立，不能把上述通用方法当成完整业务系统。

## 有条件使用

- [认知画像方法论](./workflow_cognitive_profile_extraction.md)：只在明确请求且数据处理获授权时参考；
  不把生成的个人画像自动采入长期记忆，不假定存在 Opus 或外部发布工具。
- [会话归档指南](./ai_session_search_archive.md)：外部 exporter 尚未安装，当前不 dump 会话。
  Copilot 自身会话查询优先使用当前运行时提供的历史检索。
- [Koyeb 部署](./deployment_github_actions_koyeb.md)：需要对应项目和账号，发布需授权。
- 语义搜索：暂不启用；本地文档计数达到 100 时提示，关键词连续召回失败也可提前提示。
  启用前确认数据范围、embedding 服务及成本；不自动上传。

## 外部能力目录（未安装不等于可执行）

- 写作参考入口：[内部写作](./workflow_internal_writing.md)、[外部写作](./workflow_external_writing.md)、
  [prose 诊断](./bestpractice_external_prose.md)、[thesis catalog](./reference_writing_thesis_catalog.md)、
  [prose lint](./external_prose_lint.md)。这些是迁移指针；未安装完整 writing-skill 时
  使用 `rules/COMMUNICATION.md` 的现有规范，不调用不存在的 CLI。
- AI CLI、Playwright E2E、文档工具等独立 repos 见
  [能力目录](../../docs/SKILL_ECOSYSTEM.md)。仅在任务需要且获得授权时安装。

## 不活跃区

`archive/` 不参与匹配和默认搜索。Apple/iOS、媒体、营销发布等归档文件只有在用户
要求恢复时读取，恢复前修正相对路径与依赖。新增 skill 后更新本索引，不制造第二份路由表。
