# Todoist 接入：官方 td CLI（默认通道）

核验日期：2026-10-18（td v5.5.2 实测：安装、OAuth 登录、读、写、完成全部通过）。**本 skill 的默认且推荐通道 = Todoist 官方 `@doist/todoist-cli`（td）**，与飞书侧 `lark-cli` 对称：本地 CLI 直连官方账号，不依赖宿主插件。

官方依据：npm 包 `@doist/todoist-cli`（仓库 github.com/Doist/todoist-cli，维护者均为 @doist.com，MIT 开源）。宿主的 Todoist MCP（ai.todoist.net/mcp）已于 2026-10-18 停用并摘除：该通道断线后工具全部不可用且需重启会话，用户不接受这种故障模式。

## 安装与登录

```powershell
npm install -g @doist/todoist-cli
td auth login            # 浏览器 OAuth，只需一次
td auth status --json    # 核对账号
```

- 凭据存系统凭据管理器（Windows Credential Manager / macOS Keychain / Linux Secret Store），自动续期。不要 `--read-only`（只读无法发布/改期）。
- 浏览器不便时用 `td auth login --no-browser-open` 打印授权链接，把链接交还用户。
- `td auth status --json` 的 id/fullName 必须与 config.todoist.user_id 一致；不一致立即停写，按 onboarding 换账号流程处理（暂停线上写入、新建隔离档案）。
- 本机多个账号时加 `--user <id|email>`；`td accounts list` 查看。升级用 `td update`（`td doctor` 会提示）。
- 没有 Node/npm 时先补运行环境，再继续本步。
- 不让用户粘贴个人 API token（`td auth token`/环境变量方式不作默认），也不调用 `td auth token view` 打印 token。
- Todoist 自带的 agent skill（`td skill install`）不需要安装——本 skill 已覆盖工作流。

## 常用命令（v5.5.2 实测）

| 工作 | 命令 |
|---|---|
| 今日+逾期 | `td today --json` |
| 近一周 | `td upcoming --json`（默认 7 天） |
| 收件箱 | `td inbox --json` |
| 查任务 | `td task list [--project id:X] [--parent id:X] [--due today/overdue/YYYY-MM-DD] [--filter 原生查询] --all --json`；单条 `td task view id:X --json` |
| 完成历史 | `td completed list --since YYYY-MM-DD --until YYYY-MM-DD`（可 `--search`） |
| 活动/评论 | `td activity`、`td comment list id:X` |
| 建子任务 | `td task add "标题" --project id:P --parent id:Q --due YYYY-MM-DD --priority p1..p4 --description "..." --json`；纯容器父任务加 `--uncompletable` |
| 改原任务 | `td task update id:X --due YYYY-MM-DD [--priority p1..p4] [--content ...] [--description ...]`；清日期用 `--no-due`；只传变化字段 |
| 改期（保循环） | `td task reschedule id:X <date>` |
| 移动 | `td task move id:X --project/--section/--parent ...` |
| 完成/撤销 | `td task complete id:X` / `td task uncomplete id:X` |

纪律：

- 引用一律 `id:<稳定ID>`，不用标题匹配；读一律 `--json`（大结果 `--ndjson`），翻页用 `--cursor`/`--all`。
- 写命令可先 `--dry-run` 预览；`--quiet` 压掉成功提示（create 仍会打印 ID）。
- 写后读回、来源标记去重、outbox 恢复、基线与评论指纹规则不变；td 失败时不切换其他通道重复创建。
- `--due` 原文交给服务端 due_string 解析，只喂 `YYYY-MM-DD`（服务端不解复杂语句如 "starting ..."）。
- 调用用 argv 数组/subprocess，不把用户标题/评论拼接进 shell；长描述用 `--stdin`。

## 字段形状（归一化注意）

td 的 JSON 与旧宿主 MCP 不同，归一化以本机真实输出为准（另见 script-contract.md）：

- `priority` 是数字 1-4，与归一化 p1..p4 反向对应：p1(最高)=4，p2=3，p3=2，p4=1。
- 日期是对象：`due.date`（YYYY-MM-DD）、`due.string`、`due.isRecurring`；没有 dueDate 字符串字段。
- 列表/详情 JSON 不含 checked；完成事实读 `td completed list` / `td activity`，不臆造完成时间。
- 常用字段：id、content、description、projectId、parentId、sectionId、labels、url、isUncompletable、deadline、duration。

## 应急兜底

td 不可用时先修 CLI 本身：`td doctor` 自检、重装官方包、重新 `td auth login`；仍不可用时按 onboarding 第 3 步重来。不自建第二套同步通道，不临时借用宿主凭据直连接口，也不静默降级为手工改 Todoist。长期修不好就保留聊天规划，并说明自动同步未配置完成。
