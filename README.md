# CQ-Task Management · 个人任务规划助理

和 Agent 聊天制定月度、周度计划，用飞书多维表管理项目与关键结果，用 Todoist 执行每天的具体任务。收尾时读取勾选状态和任务评论，回写进展，再调整同一条任务。

## 直接发给你的 Agent

复制下面这段，让能够读取仓库、操作本地文件的 Agent 帮你安装和配置：

```text
请帮我安装并配置这个个人任务规划 Skill：
https://github.com/EConG37/cq-task-management

先阅读仓库 README.md 和 INSTALL.md，检查源码后再执行安装。
默认安装到当前用户的全局 ~/.agents/skills/cq-task-management；已有同名 Skill 时保留其个人状态，按更新说明处理。
安装完成后读取 SKILL.md 和 references/onboarding.md，在当前对话中开始引导。
按“复制配套飞书模板到我自己的空间 → 配置飞书 CLI → 连接 Todoist”的顺序，一次只让我完成当前一步。
复用已有工具和登录；授权在官方页面完成，不向我索取密码或 API 密钥。
配置后先和我确定计划，再根据我的授权发布任务。
```

## 它能帮你做什么

- 把月度目标拆成跨周项目和可执行子任务，保留关键结果与验收标准。
- 将确认过、带具体日期的近期任务发布到 Todoist 的对应项目和父任务。
- 读取完成状态和任务评论，记录进展、困难、原因及下一步。
- 获授权后更新原任务的日期与安排，处理重复发布、冲突和部分失败。

## 安装

需要 Python 3.10+。从仓库或 [最新发布版](https://github.com/EConG37/cq-task-management/releases/latest) 下载并完整解压，在目录中运行：

```shell
python install.py
```

默认写入当前用户的 `~/.agents/skills/cq-task-management`。Windows 下通常为 `C:\Users\<你的用户名>\.agents\skills\cq-task-management`。安装器只复制公开文件；目标已存在时停止，保留原配置。具体宿主的目录适配和更新方法见 [INSTALL.md](INSTALL.md)。

如出现 IANA 时区数据缺失，使用当前 Python 环境安装 `tzdata`：`python -m pip install tzdata`。安装器本身不下载依赖、不连接账号、不写入线上任务。

## 配置与开始使用

1. 打开 [任务管理多维表｜空白模板](https://zk5ckzju3h.feishu.cn/base/H7u3bnCnYaOUh7sMJ8acMbhpn3f?from=from_copylink)，复制到自己的飞书空间，把新副本的完整链接交给 Agent。已有自己的任务表也可复用。
2. Agent 检查并配置飞书 CLI，验证你自己的账号、表格访问和字段结构；你在官方页面完成必要的授权。
3. 复用或连接同一 Todoist 账号，优先使用现有插件/MCP，也可使用官方 CLI。

首次配置后可以说：“帮我安排本周计划”“把确认的任务发布到 Todoist”“读取今天的完成情况和评论，做一次复盘”。

定时运行需要你的 Agent 宿主提供自动化能力，并另行设置时间、时区和读写范围。仅安装 Skill 不会自动开启后台同步。

## 数据与隐私

账号绑定、任务 ID、偏好和同步日志只在使用者本地状态中保存。登录凭据留在官方连接器或系统凭据管理器；不要提交个人状态、登录文件或未脱敏的聊天记录。新用户独立初始化，安装不继承作者数据。发布检查范围见 [PRIVACY.md](https://github.com/EConG37/cq-task-management/blob/main/PRIVACY.md)。

## 开发与分发

```shell
python -m unittest discover -s scripts -p "test_*.py"
python scripts/package_release.py --source . --output dist/cq-task-management-v2.0.2.zip
```

打包使用明确文件清单，排除个人 state、profiles、outbox 和缓存，并核验 ZIP 内容。不要直接压缩正在使用的整个 Skill 文件夹。

MIT License。飞书和 Todoist 的账号、服务及授权由各自平台提供。
