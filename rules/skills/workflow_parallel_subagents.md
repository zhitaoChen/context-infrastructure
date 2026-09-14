# 并行 Subagent 工作流

## 目标与边界

用于可独立探索、实现或验证的大任务。上下文隔离和独立产物是主要收益；
小任务、单条连续调用链、共享状态写入不拆分。当前运行时的委派约束优先。

## Copilot 调用约定

以当前工具 schema 为准。当前 Copilot `functions.task` 使用 `agent_type`，
不是旧 OpenCode 的 `subagent_type`。不要调用未注册的 `reasoning_gpt`、
`cheap_glm`、`private_ds4` 或 `writer_deepseek`，也不要推断某 provider 的隐私保证。

常用类型：`explore`（只读探索）、`task`（命令执行）、`general-purpose`（独立工程任务）、
`code-review`（只读审查）、`research`（调研）；具体可用集合以工具列表为准。
除非用户明确指定，不覆盖模型、推理强度或 context tier。

```json
{
  "description": "实现独立模块",
  "agent_type": "general-purpose",
  "name": "isolated-module",
  "mode": "sync",
  "prompt": "中文输出。目标、背景、负责文件、允许操作、验收标准与停止条件写清楚。"
}
```

有多个真正独立的调用时，用 `multi_tool_use.parallel` 在同一轮发出。
默认同步；仅在主 Agent 有独立工作可做时用 background。
后台任务返回 agent_id，等待完成通知后用该 ID 读取结果，不反复轮询或重复它的工作。

## 任务契约与交接

- 每个 Agent 有有界目标、必要上下文、读写范围、输出格式、验收标准和停止条件。
- 文件写入范围不重叠；共享数据库或状态由一个 owner 管理，或使用明确事务接口。
- 复杂中间产物保存在任务获准的本地 artifact 目录。交接返回路径、结论与不确定项。
- 简短结果直接返回即可，不要求所有子任务制造 Markdown。
- 主 Agent 负责整合、冲突处理和最终验收；不要让另一个 Agent 重复已完成的同一调查。
- 长任务遵循 [检查点与恢复](./workflow_long_task_recovery.md)。子进程退出不等于任务成功，
  状态与产物必须共同满足验收条件。

## 隐私与成本

不向外部模型转交未经授权的私有数据。不能因为旧文档写了零留存就认为已获授权。
不因工具存在就启用 factory/fleet；大规模编排需要明确请求。
独立角度应解决真实不确定性，而不是增加固定审查轮次。
