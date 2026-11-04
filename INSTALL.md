# Agent 安装与配置说明

本文件面向正在帮用户安装本 Skill 的 Agent。仓库地址：[EConG37/cq-task-management](https://github.com/EConG37/cq-task-management)。先查看源码和实际运行环境，再执行安装。

## 1. 下载并安装到全局目录

检查 Python 3.10+ 是否可用。获取仓库或最新 Release ZIP，完整解压后定位同时包含 `SKILL.md`、`install.py`、`scripts/` 的目录。不要将 GitHub 下载包外层目录误当 Skill 本体，不需要 GitHub 登录。

如有 Git，可在临时工作目录执行：

```shell
git clone https://github.com/EConG37/cq-task-management.git
cd cq-task-management
python install.py
```

默认安装父目录为当前用户的 `~/.agents/skills`。用户已指定全局目录时优先采用；不要硬编码作者机器路径，不要默认装进当前项目。`--skills-dir` 接收父目录，安装器会在其中创建 `cq-task-management`：

```shell
python install.py --skills-dir <当前用户指定的全局skills目录>
```

安装器只复制 `scripts/package_release.py` 的 `PUBLIC_FILES` 清单，不带入来源目录的 state、profiles、缓存、Git 历史或额外文件；不安装飞书/Todoist 工具、不读取凭据、不创建任务。

默认目录是否被自动发现取决于宿主。使用宿主明确支持的全局目录或其官方 Skill 加载机制；必须适配时先保留用户的目录偏好和已有文件。完成后检查目标目录的 `SKILL.md` 和引用文件可读。宿主需要重载时说明实际操作；当前对话仍可直接读取安装后的 Skill 并开始引导。

## 2. 保留已有用户数据

已有同名目标时，安装器停止，不覆盖。更新前检查现有安装是否也是本 Skill，备份其目录到版本控制之外的位置；保留 `state/`、`profiles/`、未完成 outbox、账号绑定和用户偏好。核对差异后仅替换公开清单中的文件，沿用自己的配置，不用 `config.example.json` 覆盖 `state/config.json`，不迁移别人的账号或任务 ID。

公开版提供作者允许分享的空白模板链接。用户已有自己的 Base 和绑定时继续复用并核验，无需重建。尚未绑定 Base 且旧本地配置没有模板入口时，仅从随包示例补齐 onboarding 的公开模板信息，保留其他本地状态。模板核验日期保留原日期，不声称本次安装已实时核验内容。

## 3. 在当前对话中开始配置

安装后立即读取安装目录的 `SKILL.md` 和 `references/onboarding.md`。不要等用户再次询问怎么配置；若用户明确暂缓，就保留进度。Skill 文件没有安装回调或后台监听器。

按当前上下文确定用户时区。新用户在安装后的 Skill 目录中初始化空状态：

```shell
python scripts/init_state.py --state-dir state --timezone <用户的IANA时区>
```

只有状态目录不存在或为空才执行；已有状态先读取。示例时区不代表使用者时区。若 `zoneinfo` 缺少 IANA 数据，在用户授权的 Python 环境补充 `tzdata`，不要将时区未知当成 UTC。

每次只引导当前未完成的一步：

1. **复制飞书模板**：展示 [任务管理多维表｜空白模板](https://zk5ckzju3h.feishu.cn/base/H7u3bnCnYaOUh7sMJ8acMbhpn3f?from=from_copylink)，引导复制到用户自己的空间，再发送新副本的完整链接；用户已有工作表也可复用。模板原链接不能直接绑定为工作库。
2. **飞书 CLI**：检查工具、应用配置和当前用户登录。缺失时按[官方安装说明](https://github.com/larksuite/cli/blob/main/README.zh.md)执行必要配置。读取自己的 Base，按 `references/structure.md` 检查并补建主任务、子任务及字段，保存现场 ID。使用当前官方 `lark-shared`、`lark-base` 说明；依赖 Skill 缺失时从官方 CLI 获取并按全局目录偏好安装，不猜参数。
3. **Todoist**：复用已有账号，Agent 统一通过[官方 CLI](https://github.com/Doist/todoist-cli)的 `td` 接入，按 `references/todoist-access.md` 操作同一个账号。

用户已明确要求安装并配置时，在该范围内继续必要步骤；遇到需要用户复制链接或 OAuth 登录的页面时，给出当前操作并等待实际反馈。授权链接使用工具本次返回的原始地址；不得收取密码、API token、appSecret 或完整凭据文件。复用已有登录，不为配置额外创建测试任务。

## 4. 验证结果后交付

确认 Skill 文件可读、本地资源配置有效、飞书可访问且字段已绑定、Todoist 当前身份及任务/评论/完成记录查询可用；写权限来自实际授权信息。`setup_check.py` 只评估给定证据，不会主动连接服务。未知项保留未知，不能只凭文件存在或 configured=true 宣称就绪。

告知已完成的连接与仍需用户操作的步骤，然后进入月度/周度规划。线上发布按用户请求和已有授权执行；首次确认发布的真实任务作为写入验收，读回后才报告成功。定时同步需要宿主的独立自动化配置；安装本身不代表已经启用。
