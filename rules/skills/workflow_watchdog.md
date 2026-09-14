# 后台任务健康检查

用于定位长任务停滞、异常退出和无效重试。默认依赖运行时完成通知，
不要为每个后台 Agent 额外创建轮询 schedule。

- 有 agent_id/shellId 时沿用该 ID，不重新发现或启动同目标任务。
- 对无通知机制的外部服务，检查新日志、产物时间、退出码和阶段检查点；
  仅 CPU 活跃或 PID 存在不能证明任务有进展。
- 不凭“很久没输出”直接 kill。先排除正常长计算，确认停止不会破坏输出。
- 确需停止时只操作该任务的确切 ID，先保存可用检查点，再采用有界重试。
- 恢复方法见 [长任务恢复](./workflow_long_task_recovery.md)，持久调度见
  [延时执行](./delayed_execution.md)。

记忆后台用 `python <brain-root>\tools\brain\memory.py status` 查看最后运行状态；
失败返回非零，详细记录在本地数据库和 `.local` 日志，不靠最后一句自然语言判断成功。
