# Skill: 分享报告到 Web

将 Markdown 报告转为 HTML 并发布到 <your-domain>/share，返回可访问的 URL。

## When to Use

用户说出以下意图时触发：
- "帮我分享一下这个报告"
- "把这个发布出去"
- "share 一下"
- "给我一个链接"
- 任何将 Markdown 文件分享给他人阅读的需求

## Prerequisites

- pandoc 已安装（本地 `/opt/homebrew/bin/pandoc`）
- SSH 到 `<your-server>` 免密登录已配置
- CSS 模板位于 `tools/share_report.css`
- GA4 追踪片段位于 `tools/share_report_ga4.html`
- TTS 语音播报片段位于 `tools/share_report_tts.html`
- 本地项目目录：`adhoc_jobs/yage_share/`（含 manifest.json、gen_index.py、site/）

## Usage

### H1 去重（必读）

`--metadata title` 会让 pandoc 自动生成一个 `<h1>`。如果 Markdown 文件第一行也是 `# 标题`，HTML 里会出现两个 h1。**发布前必须去掉 Markdown 里的 `# ` 行**，用 metadata title 单独提供 h1：

```bash
# 去掉第一行 # 标题，生成临时文件
tail -n +2 <input.md> > /tmp/<slug>_no_h1.md
# 后续 pandoc 命令使用 /tmp/<slug>_no_h1.md 作为输入
```

### 完整发布流程

#### 第 1 步：生成 SEO meta 片段

根据文章内容，生成一个临时 HTML 片段文件 `/tmp/<slug>_seo.html`，包含：

```html
<meta name="description" content="<150字以内的文章摘要>">
<meta name="author" content="<your-name>">
<meta property="og:title" content="<报告标题>">
<meta property="og:description" content="<150字以内的文章摘要>">
<meta property="og:url" content="https://<your-domain>/share/<slug>.html">
<meta property="og:type" content="article">
<meta property="article:published_time" content="<YYYY-MM-DD>">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="<报告标题>">
<meta name="twitter:description" content="<150字以内的文章摘要>">
<link rel="canonical" href="https://<your-domain>/share/<slug>.html">
```

#### 第 2 步：pandoc 转换（含 SEO + GA4 + TTS）

```bash
pandoc /tmp/<slug>_no_h1.md \
  -o adhoc_jobs/yage_share/site/<slug>.html \
  --standalone \
  --embed-resources \
  --metadata title="<报告标题>" \
  --css tools/share_report.css \
  --include-in-header=/tmp/<slug>_seo.html \
  --include-in-header=tools/share_report_ga4.html \
  --include-after-body=tools/share_report_tts.html
```

注意：输出直接写到 `adhoc_jobs/yage_share/site/` 目录。

#### 第 3 步：更新 manifest.json

编辑 `adhoc_jobs/yage_share/manifest.json`，在 `articles` 数组中添加新条目：

```json
{
  "slug": "<slug>",
  "title": "<报告标题>",
  "date": "<YYYY-MM-DD>",
  "description": "<150字以内的文章摘要>",
  "author": "<your-name>",
  "indexed": false,
  "is_temporary": false
}
```

**索引控制**（重要）：
- **默认 `indexed: false`**——文章不出现在 index.html 列表中
- 仅当用户明确说出以下意图时设为 `true`：
  - "加到索引"、"放到 index"、"公开列出"、"在索引里包括这篇"
- 不确定时，默认 `false`，事后可改

**临时标记**（可选）：
- **默认 `is_temporary: false`**（缺省即为 false，可省略）
- 设为 `true` 的触发词："临时"、"temporary"、"有时效性"、"过期可删"
- 用途：标记有时效性的内容，便于后续批量清理
- 与 `indexed` 正交：临时文章也可以被索引，非临时文章也可以不索引

#### 第 4 步：条件性更新 index.html

**仅当 `indexed: true` 时执行此步**：

```bash
cd adhoc_jobs/yage_share && python3 gen_index.py
```

这会读取 manifest.json，过滤 `indexed: true` 的文章，按日期倒序生成 `site/index.html`。

#### 第 5 步：上传到远端

```bash
# 上传文章
rsync adhoc_jobs/yage_share/site/<slug>.html <your-server>:/var/www/yage/share/
ssh <your-server> "chmod 644 /var/www/yage/share/<slug>.html"

# 如果更新了 index.html，也上传
rsync adhoc_jobs/yage_share/site/index.html <your-server>:/var/www/yage/share/
ssh <your-server> "chmod 644 /var/www/yage/share/index.html"
```

#### 第 6 步：git commit manifest 变更

```bash
cd adhoc_jobs/yage_share && git add manifest.json && git commit -m "add: <slug>"
```

### slug 命名规则

- 英文小写，单词用 `-` 连接
- 结尾加日期 `YYYYMMDD`
- 例：`iran-war-survey-20260302`、`ai-agent-report-20260315`

### 最终 URL

```
https://<your-domain>/share/<slug>.html
```

## 验证

上传后用 curl 确认可访问：

```bash
curl -s -o /dev/null -w "%{http_code}" https://<your-domain>/share/<slug>.html
# 应返回 200
```

## CSS 模板说明

`tools/share_report.css` 特性：
- 800px 最大宽度居中排版
- 中文字体栈（PingFang SC / Microsoft YaHei）
- 自动暗色模式（prefers-color-scheme: dark）
- 表格、引用块、代码块样式
- 移动端响应式适配

如需修改全局样式，编辑 `tools/share_report.css`，后续发布会自动使用新样式。

## 包含图片的报告

当 Markdown 中引用了本地图片（`![](path/to/image.png)`）时：

```bash
# 用 --resource-path 指定图片搜索目录（通常是 MD 文件所在目录）
pandoc <input.md> \
  -o adhoc_jobs/yage_share/site/<slug>.html \
  --standalone \
  --embed-resources \
  --resource-path=<md文件所在目录> \
  --metadata title="<报告标题>" \
  --css tools/share_report.css \
  --include-in-header=/tmp/<slug>_seo.html \
  --include-in-header=tools/share_report_ga4.html \
  --include-after-body=tools/share_report_tts.html
```

`--embed-resources` 会将图片转为 base64 data URI 内嵌到 HTML 中。

发布前验证：
```bash
# 确认图片已内嵌
grep -c 'data:image' adhoc_jobs/yage_share/site/<slug>.html
# 应输出图片数量（>0）
```

## TTS 语音播报

`tools/share_report_tts.html` 通过 `--include-after-body` 自动注入到每篇报告中，提供：

- 右下角浮动 🔊 按钮，点击朗读、再点暂停，长按 0.8 秒停止
- 基于浏览器原生 Web Speech API（`speechSynthesis`），零后端、零成本
- 自动跳过代码块和表格，按中文标点断句（每段约 200 字）
- 内置 Chrome 14 秒中断 bug 的 workaround（分段播放 + 定期 pause/resume）
- 不支持 `speechSynthesis` 的浏览器自动隐藏按钮

如需修改 TTS 行为（语速、分段长度等），编辑 `tools/share_report_tts.html`。

## 注意事项

- HTML 是自包含的（CSS + GA4 + 图片 + TTS 均内嵌），不依赖外部文件
- share 目录公开可访问，不要上传敏感内容
- 如需删除已发布内容：`ssh <your-server> "rm /var/www/yage/share/<slug>.html"`
- **重要：使用 `--metadata title` 时，Markdown 文件的第一行不应该是 `# ` 标题**。pandoc 会从 metadata 自动生成一个 h1 元素，如果 Markdown 中还有 `# ` 标题，HTML 输出会出现两个 h1 元素。解决方案：删除 Markdown 中的 `# ` 标题行，让 pandoc 的 metadata title 单独提供 h1。
- 本地项目目录 `adhoc_jobs/yage_share/` 是 manifest 和 site 的 source of truth
- `site/` 下的 HTML 文件被 .gitignore 忽略，只有 manifest.json 和脚本被 git 追踪
