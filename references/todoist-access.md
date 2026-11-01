# Todoist 接入：MCP/插件与无 MCP 的 CLI

接入入口与安装方式核验日期：2026-11-01；具体子命令仍须查本机 help。优先使用当前已连接、可用的工具；改 transport 不改变 Todoist 账号、Base scope 或任务 ID。先验证同一 user_id，否则进入新账号配置，不能把已有任务映射迁到另一账号。

## MCP

Todoist 官方远程地址为 `https://ai.todoist.net/mcp`，使用 Streamable HTTP + OAuth。通常只配置地址并登录，不必下载安装包。官方仓库也提供本地 npm 运行方式；默认不采用需要用户粘贴 API key 的本地方案。

Todoist 工具名称/参数以当前 MCP schema 为准，兼容本 skill 已有 user-info、find-tasks、fetch-object、find-comments、find-activity、add-tasks、update-tasks 和 complete-tasks 等语义。首次只读检查账号与数据；不因为工具可见就认为已授权。

## 无 MCP：官方 td CLI

这是可直接被 skill 调用的替代通道，无需实现另一套任务系统。当前环境已经可用 MCP 时，不额外安装 CLI。

用户选择/授权 CLI 配置后，检查 Node/npm 和官方 CLI 当前要求，优先复用已安装 td。需要安装时使用官方包：

```powershell
npm install -g @doist/todoist-cli
td auth login
td auth status --json
td accounts current --json
```

OAuth 打开浏览器，凭据默认存入 Windows Credential Manager/macOS Keychain/Linux Secret Service。不可默认降级为明文保存，也不调用 td auth token view 把 token 打印出来。只读登录可用 td auth login --read-only，但此模式无法发布/改期。

安装此 CQ-Task Management 本身不需要再安装 Todoist 附带 skill。若用户另需官方 skill，遵守其全局目录偏好；本环境使用 `td skill install universal` 对应 ~/.agents/skills，先核对当前 CLI 帮助，不能按 Codex 专用选项写到其他目录。

每次先查具体子命令 --help，优先 --json 完整读取，使用 id:<稳定ID> 避免模糊标题匹配。调用用 argv 数组/subprocess，不拼接用户标题/评论进 shell；描述和反馈含长文本时选支持的 stdin/file 输入。支持 --dry-run 才使用，不假定所有命令支持相同分页 flag。

| 工作 | CLI 命令族 |
|---|---|
| 账号/项目 | td auth status、td accounts current、td project list/view |
| 查任务/单个任务 | td task list、td task view id:<taskId> |
| 已完成/撤销事件 | td completed list、td activity |
| 读任务评论 | td comment list id:<taskId> |
| 创建子任务 | td task add，显式 --project id:<projectId>、--parent id:<parentId>、--due YYYY-MM-DD、--priority p1..p4、--description |
| 更新原任务 | td task update id:<taskId> --due YYYY-MM-DD；只传实际变化字段 |
| 完成/撤销 | td task complete id:<taskId>、td task uncomplete id:<taskId> |

表中只表示已核验的命令族与核心选项，flags 以本机 help 为准。读取任务/评论/完成记录都完整翻页；--all、--cursor、--limit 的支持随命令族而异。Task JSON 的 completed_at/is_completed/checked、due、parent_id 等字段可能与 MCP 的 camelCase 不同，依据本机真实输出归一化到 script-contract.md；日期以用户时区转换，不改变真实完成时间。

CLI 的正常写入 scope 只表明技术可用，本次发布/改期仍需用户授权。写后读回、标记去重、outbox 恢复、基线及评论指纹规则与 MCP 完全相同；失败时不切另一通道重复创建。

## 官方来源

- [Todoist 开发者平台](https://developer.todoist.com/)：远程 MCP、统一 API、CLI。
- [官方 MCP 仓库](https://github.com/Doist/todoist-mcp)：不同宿主接入说明。
- [官方 CLI 仓库](https://github.com/Doist/todoist-cli)：安装、OAuth、凭据保存及支持命令。

官方 API 也支持任务和评论；仅当 CLI/MCP 不满足需求且用户明确需要自定义适配时，使用官方当前 API v1 或 SDK。普通用户优先 OAuth + CLI，避免要求粘贴个人 API token。
