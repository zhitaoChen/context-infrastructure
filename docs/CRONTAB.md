# Windows 自动记忆计划

使用 Windows Task Scheduler 调用 `run.ps1`，不依赖打开的 Copilot 聊天。
原会话内 schedules 仅适合临时提醒，不作为每日/每周后台运行器。

| 任务名 | 北京时间 | 行为 |
|---|---|---|
| `PersonalBrain-Daily` | 每日 00:00 | 采集引用 → Observer 自动提炼工作流请求 → 分类入库 |
| `PersonalBrain-Weekly` | 周日 23:30 | Reflector 自动生成完整 skill／公理草稿，等待审阅 |

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
每日最多两次模型调用，任务上限默认 22 分钟；每周一次，默认 12 分钟。
两者均额外预留 120 秒。无合格输入时不调用模型，不进行无限重试。

## 数据流与恢复

```text
获准的本地 Copilot 历史 -> 只读扫描 -> SQLite 历史引用队列
  -> 本地排除自动提示、敏感内容和不可独立理解的片段
  -> Observer: 有界工作流请求 -> 方法候选 + 引用处理结果（同一事务）
  -> 需本地审阅的内容保留 needs_review，不进入模型
Agent 主动 capture -> SQLite pending
  -> daily: 受限 Copilot 返回完整 ID 决策 -> SQLite accepted/rejected
  -> weekly: 受限 Copilot 返回提案 -> .local\reviews
  -> 用户审阅 -> 明确编辑规则
```

后台模型没有文件或 shell 工具，也不加载全局用户指令。Observer 复用已配置账号的
Copilot，对授权历史中经过本地筛选的独立用户请求进行提炼。
分类器和 Reflector 只接收提炼后的方法候选，不接收聊天原文或助手输出。
本地程序验证输出再写数据库。不同来源的重复出现只是提案的
最低条件，不自动证明正确。原始证据保留，不自动删除 accepted 内容或改写 USER。

SQLite 是事实来源；生成视图失败可用 `render` 重建。
模型/验证失败不消费 pending；异常退出的运行标记可在下次启动识别。
运行锁只串行化后台整理，不阻塞其他会话的独立 capture 事务。
周度最多处理 128 条，优先未审阅观察，并保留最多 32 条已审阅观察作为对照。
其余继续保留，`remaining_unreviewed` 报告积压，不会因总量增长而永久停止。
每份提案保存实际输入 ID；没有新观察时不重复生成同一批草稿。

周度 Reflector 输出完整的 skill / axiom 草稿，而不只是提纲；每条正文最多 6000
字符，包含适用范围、验收或反例、证据与局限。不同会话对同一方法的独立佐证可以
同时保留；重复自动提示、同一事件的复述不构成独立证据。完整草稿仍需审阅后才生效。

## 启用本地历史引用采集

采集范围必须由用户确认。下面仅是占位示例，不会因安装任务自动启用：

```powershell
python .\tools\brain\history.py configure --repository '<owner/repository>' --backfill-days 30 --confirmed
```

可重复指定 `--repository`；只有用户明确授权全部仓库时，才改为 `--all-repositories`。
未识别所属仓库的会话不采集；全仓库模式也不会把这类会话算入。0 天表示只从启用时刻起，
30 天表示首次回补 30 天，此后继续采集，而不是每天丢弃 30 天前的未处理记录。
配置已有时先核对范围，再用 `--replace`；旧候选不会因此删除，范围外的旧引用禁止提炼。

默认只读连接 `$HOME\.copilot\session-store.db`，也可用 `--database '<absolute-path>'`
指定本地源。不创建软链接，不修改 Copilot 数据库，不导出原文，也不调用模型。
这是经结构检查的本地格式适配器，不是 Copilot 对历史格式永久兼容的承诺；
只覆盖本机已落盘的会话，不保证覆盖云端或其他设备的所有历史。
路径不存在或结构不兼容会明确失败，且不推进游标。

每次最多扫描 5000 条符合范围的记录，队列与游标事务提交；`more=true` 表示仍有积压，
可再次执行 `collect` 继续，不能把它当作全量回补完成。优先按高水位读取新增轮次，
再用剩余预算按独立游标循环核对旧记录，防止历史积压拖延新输入。
核对用于发现旧轮次补写或修改，不重复入队，也不会做全量模型重算。
最近两分钟的轮次留到后续扫描，减少尚未完成的响应反复更新。
已修改的待审版本标为 superseded，新版本重新待审；已提炼记忆不会自动改写或撤回。

```powershell
python .\tools\brain\history.py collect
python .\tools\brain\history.py list --limit 20
python .\tools\brain\history.py disable
```

每日和每周 runner 在整理前调用采集器。旧安装无需重建计划任务；更新 runner 后即生效。
未配置/已停用时会显式记录 skipped，保留原有直接 capture 流程；
启用后采集失败则整个 runner 返回非零，不继续用旧输入掩盖错误。
配置独立保存在 `.local\history.json`，重新安装定时器不会覆盖它。

## 启用定时 Observer

用户确认定时提炼后执行：

```powershell
python .\tools\brain\observer.py configure --confirmed
```

配置独立保存在 `.local\observer.json`。安装计划任务不会代替这项授权；
已启用后不需要用户逐次提醒。每日 runner 自动先运行 Observer，再进行分类。
旧计划任务需按上述安装命令加 `-ReplaceExisting` 更新每日执行时限，
但无需更换账号、触发时间或 Windows 登录身份。

每次优先检查较新的待处理引用，最多扫描 5000 条、送入模型 16 条独立用户请求，
每条最多 4000 字符；每条最多提炼两条方法。未处理积压留待下次。
不读取附件，不发送助手回答或工具输出，不复制原始聊天到 brain。
自动提示、系统通知和普通继续指令不作为用户偏好证据。

内部仓库命名空间、过长文本、代码或链接、疑似凭据和个人/业务敏感内容进入
`needs_review`，不会发送给后台模型。模型还会拒绝不能安全抽象或没有长期依据的内容；
它的输出需要通过本地字段、来源和内容检查，再经独立的 daily 分类。
本地过滤是保守的风险控制，不是对任意自然语言隐私的数学保证；
不要为了清空队列放宽检测或把被拦内容拼回模型输入。

```powershell
python .\tools\brain\observer.py run
python .\tools\brain\history.py list --state needs_review --limit 20
python .\tools\brain\observer.py disable
```

禁用仅停止自动提炼，采集和已有候选整理保留。被拦内容可在获授权的交互中审阅，
只提交安全抽象，流程见 [记忆采集入口](../contexts/memory/INBOX.md)。
模型、结构验证或来源版本核对失败时整批不消费，并让计划任务返回非零。

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
空记忆输入时分类仍可显示 skipped，即使前面的历史引用采集已成功；
分别查看 `history`、`observer`、`daily`/`weekly` 运行结果及待提炼、需审阅计数。
失败返回非零；不要只看任务 State=Ready。

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
