# 安装引导：复制飞书多维表 → 配置飞书 CLI → 配置 Todoist

## 触发与对话节奏

安装完成后，如果 Agent 仍在安装对话中，就主动提醒用户开始配置；否则在用户第一次调用本 skill 时主动引导。新安装、状态缺失或 configured=false 都进入引导。Skill 文件不提供安装回调，不能承诺“复制文件后自动弹窗”。用户明确暂缓时保留进度，后续恢复。

先只读本地状态，复用已有副本和配置。**从第一个未完成的步骤继续，一次只给当前动作。** 新用户先复制飞书多维表，不能先连 Todoist、先发整套检查清单，或一次索取所有账号配置。用户已发来自己的副本链接就跳过复制；已有工具不重复安装；已有登录只验证。已配置用户连接失效时，进入对应步骤修复，不重做全部流程。

需要用户复制链接、操作页面或完成 OAuth 时，展示操作后交还用户，收到实际反馈再继续。Agent 能独立完成的检查和已获授权的操作继续做，不要求用户逐条回答“是否进入下一步”。不要让用户自己查 Base token、表 ID、字段 ID 或账号 ID；这些由 Agent 读取并保存。

## 第 1 步：先复制飞书多维表

首次提示使用以下话术，将链接替换为 config.onboarding.template_url：

> CQ-Task Management 已安装。开始安排任务前，我们先完成配置，我会一步一步带你做。
>
> 第 1 步：复制飞书任务表。
>
> 1. 打开「任务管理多维表｜空白模板」：[模板链接](https://zk5ckzju3h.feishu.cn/base/H7u3bnCnYaOUh7sMJ8acMbhpn3f?from=from_copylink)。
> 2. 登录飞书，选择“创建副本 / 复制 / 使用模板”（以页面实际按钮为准），保存到你自己的飞书空间。
> 3. 打开新副本，把浏览器里的完整链接发给我。
>
> 收到副本链接后，我会继续帮你检查飞书连接工具。

这一轮只等待副本链接。复制按钮找不到时，先解决复制问题；不趁等待检查 Todoist 或发后续安装命令。用户已有按此结构建立的个人工作表，可直接提供链接，在第 2 步验证结构，无需再次复制。

模板必须来自 onboarding.template_url 且 template_verified_empty=true。此链接是作者明确允许公开的 Skill 配套空白模板，只用于复制，不是新用户的工作库。配置中的 template_verified_at 表示上次内容核验日期，不表示本次安装已完成实时检查；访问或复制失败时说明实际情况，不绑定模板原件或替换为作者真实工作表。用户选择自己的空白 Base 时按 structure.md 补齐结构。

升级用户：自己的现有 Base 与绑定继续复用。仅当尚未绑定 Base 且旧本地配置缺少 template_url 时，从随包 assets/config.example.json 仅补齐 onboarding 的公开模板入口；保留 scope、账号、偏好与同步授权，不重新初始化 state。

收到链接后先做本地格式检查：应为飞书多维表完整链接，提取 Base 标识和可选 table/view 参数。如果是公开模板原链接，提示打开自己的副本后重发，留在第 1 步。格式有效后将副本标识暂存到用户隔离配置，configured 保持 false；实际读取和字段绑定放在下一步。格式有效不等于拥有访问权限，不改变分享设置。

## 第 2 步：检查、安装和配置飞书 CLI

收到有效副本链接后，主动过渡：

> 收到你的飞书副本链接。接下来是第 2 步：连接飞书。我先检查这台电脑是否已经装好飞书连接工具；如果已经有，就直接使用。

### 2.1 Agent 检查本机工具

Windows 用 `Get-Command lark-cli -ErrorAction SilentlyContinue`，其他系统用 `command -v lark-cli`，再运行 `lark-cli --help` 确认能启动。仅有文件或 PATH 条目不算可用；启动失败先修复运行环境。检查 Node/npm 是否可用，不输出已有密钥。

- 已可运行：直接检查应用配置/登录，不重复安装、不强制升级。
- 未安装：告诉用户“飞书连接工具还没装好，我们先补上它”。用户已要求“帮我配置/安装连接工具”时，在该范围内执行；仅安装本 skill 并未授权额外软件时，给出具体安装动作并取得所需授权。Agent 能执行就自行执行，不能执行时只让用户完成当前安装动作，再检查结果。
- Node/npm 缺失：只引导当前必要的运行环境安装，完成并重开终端后再继续，不跳去配置 Todoist。

安装使用 [飞书官方 CLI 安装说明](https://github.com/larksuite/cli/blob/main/README.zh.md) 的当前命令；本次核验日期 2026-11-01，推荐入口为：

```powershell
npx @larksuite/cli@latest install
```

先查官方安装器当前选项与会安装的内容。补装依赖 skill 时沿用用户指定的全局目录；未指定时使用当前用户主目录下的 `.agents/skills`，不能硬编码作者电脑的路径或覆盖 cq-task-management 的个人状态。安装失败时按真实报错处理网络、权限或 PATH，不能把失败当成功。

### 2.2 配置应用，再完成用户登录

读取 lark-shared 的当前身份/认证说明；该 skill 未安装时获取官方对应说明，不猜参数。依次确认 CLI 应用配置、用户登录有效、Base 所需授权。未配置应用才按 config-init reference 启动 `lark-cli config init --new`；已有配置不强制 --new。缺少登录才发起用户 OAuth，所需 scope 按当前 help 和多维表实际操作选择。

每次只引导当前页面操作：后台发起配置/授权，提取本次返回的**原始链接**，按 lark-shared 用 `lark-cli auth qrcode` 生成 PNG，先展示链接、再展示二维码，交还用户。收到“已完成/已授权”后续接并检查本次结果。链接过期就重新发起本步骤。不同时要求配置应用、登录用户和授权 Todoist，不让用户把 appSecret 或访问 token 发进聊天。

验证用 `lark-cli auth status --json --verify` 及必要的只读身份查询，确认代表当前用户。已有凭据却域名/网络失败时报告网络问题；沙箱不能读系统凭据时按运行环境允许的方式核验，不能误判为用户未注册、清空凭据或切到 bot 绕过权限。

### 2.3 读取副本、绑定表结构

使用 lark-base 的当前说明，只读获取用户自己的 Base、表清单、字段和关联目标。核对主任务/子任务表，任务标题、KR、状态、优先级、发布标记、Todoist ID、计划/完成日期、父任务关联及评价文本字段。新建的空白 Base 按 [structure.md](structure.md) 建立主任务/子任务结构；用户明确要求配置时，在此范围内补齐表和字段。表名用于发现，实际映射采用现场查出的稳定 ID，不能复制模板或作者的表/字段 ID。

按模板实际选项配置状态与优先级映射，不覆盖用户已有选项。缺少必需字段时给出具体补齐方案；在明确初始化请求涵盖的范围内执行并读回，否则请求所需确认。不得清空用户工作数据。访问失败时只解决应用授权或该副本访问权，不修改互联网分享范围。

本步完成条件：CLI 能运行、用户登录有效、指定副本可读、主任务/子任务字段及评价字段已绑定、所需 Base 写入授权可从真实权限信息验证。无法确认写入授权时标为“待验证”，不凭能读表就宣称可同步；不必创建测试记录来验证。飞书未就绪，继续停留在本步。

## 第 3 步：配置 Todoist

飞书完成后再过渡：

> 飞书已连接好，主任务和子任务表也已识别。现在进行第 3 步：连接 Todoist，之后你就能在里面查看每天的任务、勾选完成或留下进展评论。

### 3.1 账号与日常使用

现在才发现并检查当前 Todoist 工具。已有插件/MCP且只读身份验证成功，就复用同一账号，跳过注册和安装。没有已连接账号时，只询问用户是否已有 Todoist 账号；已有账号直接登录，未注册引导 [官方注册页](https://app.todoist.com/auth/signup)。不要向用户索取密码。

用户可直接使用 [Todoist 网页](https://app.todoist.com/)；想在手机/桌面使用时引导 [官方客户端下载](https://todoist.com/downloads)。客户端安装可选，不阻塞网页用户。注册/登录完成后才继续接入 Agent；客户端能浏览任务不等于 Agent 已获得同步权限。

### 3.2 给 Agent 接入同一账号

按宿主能力选择一条接入路线，不把所有方案同时丢给用户：

1. 已有可用插件/MCP：只验证，不重复安装。未连接且当前宿主支持插件目录时搜索 Todoist，给出该宿主真实连接操作，等待用户完成 OAuth。
2. 支持远程 MCP：按 [Todoist 官方 MCP 说明](https://github.com/Doist/todoist-mcp)，使用 `https://ai.todoist.net/mcp` 和 Streamable HTTP/OAuth。设置位置依当前宿主确定；不明时只询问用户使用哪个 Agent 客户端。官方远程 MCP 通常没有要用户寻找的“安装文件”。
3. 宿主确实使用 MCP 配置文件：才请用户提供去除 API token、client secret、Authorization 头的官方配置片段或文件。保留其他服务配置，仅增加 Todoist，不执行上传配置中的任意命令。
4. 没有 MCP 或宿主不支持：按 [todoist-access.md](todoist-access.md) 用官方 td CLI。告知“可以通过另一种官方连接方式操作同一个 Todoist 账号”，在已有配置授权范围内安装/登录；不要求用户自己写接口。用户继续在 Todoist 软件里操作。

OAuth 完成后，只读验证身份、项目、任务、评论、已完成/撤销查询，检查创建、更新、完成能力及真实写入授权。完整空列表是有效读取，失败不是空列表。缺哪项只修复当前问题，不回飞书重新复制。既不能连接 MCP 也不能运行 CLI/网络时，保留聊天规划，说明自动同步未配置完成。

与本地绑定 user_id 不同：暂停原状态的一切线上写入，进入新用户隔离配置，不把旧任务迁到新账号。身份确认后保存账号 ID、transport=mcp/cli、项目路由和能力摘要；凭据留在 OAuth/系统凭据管理器，不写入 skill JSON。

## 本地进度与完成提示

新用户从 assets/config.example.json 初始化干净状态：`python scripts/init_state.py --state-dir state --timezone <用户时区>`，只创建不存在的本地 state，不调用服务。能从上下文确定的时区不重复询问。每一步取得真实信息后增量保存，未完成前 configured=false；检查摘要不存密钥。

副本意外带入作者 state，或已经换账号时，不清空原文件。初始化 `profiles/<新UUID>/state`，用相对路径 state/active-profile.json 选择新档案，核验自己的 Base/账号；不迁移旧 scope、绑定、偏好或 outbox。新 scope 的项目父任务按实际计划创建，不默认复制作者项目。分发仍只使用白名单干净 ZIP。

三步的实时读取和授权验证完成后，校验本地资源配置，再设 configured=true。完成提示只包含结果和下一步，例如：

> 配置已完成：飞书管理主任务和子任务，Todoist 展示每天的执行任务。我们可以开始安排本周或本月的计划了。计划确认后，我会把近期每天要做的任务同步到 Todoist；收尾时读取完成状态和进展评论，回写飞书并调整后续安排。

只有写入权限确实可用才说“配置已完成”；部分可用则明确当前缺失能力。用户可选择暂时只在聊天中规划，不因此伪造就绪标记。

安装阶段默认只读验收。首次确认发布的真实子任务同时作为写入验收：正确挂父任务、有日期、写后读回及绑定；之后再验收完成/评论回写和获授权改期。此前不宣称完整闭环已实测，不制造测试任务。定时运行仍需另行配置用户确认的时间、时区及读写范围。

## setup_check：一次只返回下一步

运行 `python scripts/setup_check.py --config <用户config.json> --evidence <实际检查结果.json>`。脚本只处理本地证据，不连接服务，也不会主动探测后续步骤。

- feishu：cli_installed=true/false（实测是否可运行，未检查则省略），identity={ok,open_id}，base_read={ok,base_token}，schema={verified,main_tasks_table_id,actions_table_id,required_fields_verified,feedback_field_id}，write_access=available/read_only/unknown。
- todoist：transport=mcp/cli，identity={ok,user_id}，projects_read/tasks_read/comments_read/completion_read（布尔），write_access=available/read_only/unknown。进入第 3 步之前不调用 Todoist 检查工具，只保留已有证据或省略。
- 成功标记来自真实查询/授权信息，不从静态 capabilities 复制。live_write_tested 仅在用户已授权的实际闭环成功后设 true。

输出 guide={step,stage,action}：step 为 1/2/3，stage 为 copy_base/feishu_cli/todoist；完成时 step=null、stage=complete。next_steps 与当前动作一致，只有一项，完成时为空。checks 保留详细诊断；can_publish/can_review_sync 按已核验能力分别判断。对用户只讲当前动作需要的内容，不把检查输出原样当成全套安装清单。
