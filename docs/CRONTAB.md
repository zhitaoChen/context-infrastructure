# Windows 自动记忆计划

使用 Windows Task Scheduler 调用 `run.ps1`，不依赖打开的 Copilot 聊天。
原会话内 schedules 仅适合临时提醒，不作为每日/每周后台运行器。

| 任务名 | 北京时间 | 行为 |
|---|---|---|
| `PersonalBrain-Daily` | 每日 00:00 | 对 pending 候选分类，一批最多 32 条 |
| `PersonalBrain-Weekly` | 周日 23:30 | 生成规则建议，等待用户审阅 |

用户输入的 24:00 等价于次日 00:00。系统时区必须为 `China Standard Time`。
使用当前 Windows 用户、Interactive 登录类型、Limited 权限；锁屏可运行，
关闭 Copilot 不影响。注销或关机时无法执行，登录/开机恢复条件后由系统尝试补跑。
不保证设备睡眠时唤醒，也不是全天在线服务器。

## 安装与账户

前提：Python 3.10+、PowerShell 7、Copilot CLI、已登录的 `gh`。
在仓库根目录执行，替换账号占位符：

```powershell
.\periodic_jobs\ai_heartbeat\install.ps1 -GitHubUser '<github-login>' -WhatIf
.\periodic_jobs\ai_heartbeat\install.ps1 -GitHubUser '<github-login>'
```

安装器拒绝默认覆盖同名任务。确认旧任务属于本系统后，可加 `-ReplaceExisting`。
不用保存 Windows 密码；每次运行按指定账号从 `gh` 凭据管理器读取授权，
只传到 Copilot 子进程环境，不切换 gh 活跃账号、不落盘 token。
已有授权失效/权限不足时任务明确失败，需本机重新登录，不在聊天提供凭据。

配置在 Git 忽略的 `contexts\memory\.local\config.json`。
按用户选择不设 AI Credits 上限；单次模型调用默认 600 秒超时，
系统任务上限额外预留 120 秒。无合格输入时不调用模型，不进行无限重试。

## 数据流与恢复

```text
Agent 主动 capture -> SQLite pending
  -> daily: 受限 Copilot 返回完整 ID 决策 -> SQLite accepted/rejected
  -> weekly: 受限 Copilot 返回提案 -> .local\reviews
  -> 用户审阅 -> 明确编辑规则
```

后台没有文件或 shell 工具，也不加载全局用户指令。模型只接收已由采集方确认非敏感的
工程方法/工作流偏好；本地程序验证输出再写数据库。不同来源的重复出现只是提案的
最低条件，不自动证明正确。原始证据保留，不自动删除 accepted 内容或改写 USER。

SQLite 是事实来源；生成视图失败可用 `render` 重建。
模型/验证失败不消费 pending；异常退出的运行标记可在下次启动识别。
运行锁只串行化后台整理，不阻塞其他会话的独立 capture 事务。
周度输入超过 128 条会明确要求整理规模，不静默漏读。

## 查看、执行与停用

```powershell
python .\tools\brain\memory.py status
Get-ScheduledTask -TaskName 'PersonalBrain-Daily','PersonalBrain-Weekly'
Get-ScheduledTaskInfo -TaskName 'PersonalBrain-Daily'
Start-ScheduledTask -TaskName 'PersonalBrain-Daily'
python .\tools\brain\memory.py render
```

`.local\daily.log`、`.local\weekly.log` 保存最近一次的命令结果；
数据库 `runs` 表保留运行历史。`LastTaskResult=0` 只表示本次程序成功，
空输入时应同时显示 skipped。失败返回非零；不要只看任务 State=Ready。

用户明确审阅并完成规则修改（或决定不采用）后记录结果：

```powershell
python .\tools\brain\memory.py resolve-review --id '<review-id>' --decision dismissed --note '用户确认已有等效规则' --confirmed
```

实际应用完成时使用 `--decision applied`。命令只记录审阅结果，不执行规则编辑，
也不能代替用户授权。

停用时只操作确切任务名：

```powershell
Disable-ScheduledTask -TaskName 'PersonalBrain-Daily'
Disable-ScheduledTask -TaskName 'PersonalBrain-Weekly'
```

更新 CLI 后先执行一次安全样例，确认零工具白名单和 JSONL 事件格式仍兼容。
不将 `.local`、本机用户配置、日志、测试会话或凭据提交到公开 Git。

## 语义搜索与旧实现

本地程序统计 `contexts` 下 report/review/session 等 Markdown 文档，
排除索引、archive 与符号链接；100 篇起返回 `suggest_enable=true`。
Agent 在查看状态时提示用户，不自动上传、计费或安装 embedding。
关键词召回困难可由交互 Agent 提前提示，不依赖一个未实现的自动失败计数器。

OpenCode 与外部 jobs 留在 `archive`，不执行。归档是保留源码，不承诺移动后可直接运行；
恢复前重新检查路径、imports、认证和平台依赖。
