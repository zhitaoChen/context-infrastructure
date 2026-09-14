# 记忆采集入口

只采集经验证、可复用的工程方法和明确的非敏感工作流偏好。
不记录身份、个人画像/推断、工作履历、财务/健康/法律/关系信息、机密业务数据、
源码、凭据或原始会话。用户主动提出也不应将这些内容写入长期记忆。

## 写入

多个会话不能手动追加同一个 Markdown。使用标准库 CLI，经 SQLite 事务写入，
返回内容寻址的记录 ID；重复提交不会重复计数。

在 PowerShell 中，把以下 JSON 通过 stdin 传入 `python <brain-root>\tools\brain\memory.py capture`。
不改变目标项目 cwd；脚本从自身路径定位中央 brain。

```json
{
  "source": "非敏感证据来源标识，例如公开测试名称",
  "observation": "简短且未来可执行的方法",
  "evidence": "已经验证的依据，不含源码或机密",
  "non_sensitive": true,
  "durable": true
}
```

只有确认满足隐私与长期价值条件时才设置两个 true。程序的凭据检测只是辅助，
不能自动证明数据安全。没有合格内容时不写入。采集失败须报告，不能声称已记住。

## 读取与健康

- 待处理视图：`contexts\memory\.local\INBOX.md`
- 接受的记忆：`contexts\memory\.local\OBSERVATIONS.md`
- 待人工审阅：`contexts\memory\.local\reviews\`
- 健康状态：`python <brain-root>\tools\brain\memory.py status`
- 从数据库重建视图：`python <brain-root>\tools\brain\memory.py render`

用户明确审阅后，用 `resolve-review --id <review-id> --decision applied|dismissed
--note <非敏感依据> --confirmed` 记录处理结果。`applied` 仅在获授权的规则修改已完成后使用；
该命令本身不应用任何规则。状态会持久化，已处理提案不再列为待审。

`.local` 已被 Git 忽略。Markdown 是可重建视图，不直接编辑。
捕获依赖 Agent 主动执行这个入口，不是强制 session-end hook，不 dump 对话。
