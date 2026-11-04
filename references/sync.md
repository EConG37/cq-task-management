# 多维表 ↔ Todoist 同步协议

## 身份、字段与授权

`mappings.scopes[scope].main_tasks` 记录主任务→{todoist_id, project_id}；`actions` 只记录子任务→Todoist ID。绑定冲突不能靠标题解决。config、mappings 是资源快照，真实操作前读回验证。新增主任务时先在多维表主任务表建记录；需要发布执行任务时再创建获授权的 Todoist 容器（无日期，可使用 isUncompletable），记录路由。

多维表负责结构、名称、验收；Todoist 负责执行日期、优先级、勾选完成/撤销。更改任一执行字段前比对基线；首次接管发现差异时呈现当前值，让用户决定采用哪一边。一致的初始值可直接保存为读回基线。`publish` 表示发布已经落地，**不是创建任务的授权**。

事实回写、评价回写、新建发布、排期修改是不同范围。当前会话明确指令或已确认方案授予对应一次操作；持续同步须记录 approved_fields、runner、完整 automation_ids。不因为基线文件为空而反复要求确认相同方案。

## 新任务发布与恢复

1. 限定确认的具体子任务和日期窗口（连续至多 7 天）。读主任务绑定对应的父任务，核对其真实 projectId、开放/容器状态；查既有子任务绑定与 `state/outbox`。
2. 新任务描述包含 `source_marker(scope, action_id)` 输出的稳定标记。保留既有 `[goal-flow:…]` 格式以便找回旧任务；查标记时覆盖活跃和已完成任务，不只查今日。多个候选或查询不完整则暂停该任务的创建。
3. 准备 outbox 日志，记 run_id、scope、来源记录、目标路由、操作内容和前置快照，状态 prepared。确认前置快照未被其他会话修改后再创建。每个外部步骤前后更新日志。
4. 创建后立即记录返回 ID；读回 Todoist 核验日期、名称、优先级、项目、父任务和标记，日志改为 todoist_verified。多维表回写 publish=true、todoist_id、planned_for；读回后改为 base_verified。
5. 用两边最终快照验证并提交本地映射/基线，最后标 committed。已有绑定直接复用，不再创建。

API 超时/返回不明时日志标 write_unknown：先查返回 ID、标记、活动记录与日志，不盲目重发创建。创建已成功但多维表失败，只补回写和本地状态。批量部分成功逐条保存证据，不能重试整个成功批次。旧日志只供历史核对，不直接重放旧 payload。

## 完成事实与评论

按 [daily-review.md](daily-review.md) 读取。已完成任务按真实 completedAt 回写 done；撤销完成清 completed_at 并恢复开放步骤状态，不自动重开已验收主任务。日期/优先级直接从 Todoist 回写，除非多维表相对上次基线也有冲突变更。找不到不是完成；循环任务转为逐次记录或待用户选择，不能直接永久关闭步骤。

## 调整原任务

**改期/改内容前先读该任务的评论**（`td comment list id:<id>`）——用户可能在评论里留了最新进展或指示（如"前半段做完了，还差后半段""这几条留到下周集中验证"），评论优先于我的默认假设；读完评论再动手，且调整结果要吸收评论信息。

先读回确认执行事实/评价已进入多维表，再使用获授权的具体改动更新 Todoist 原 ID。改期传 `dueString`（明确 YYYY-MM-DD），返回和读回的日期叫 `dueDate`。只传变化字段；无移动时不传 projectId/sectionId/parentId。跨项目移动是单独获授权的结构变更，并再次核对父任务。

更新 Todoist 并读回后，回写多维表计划日期/优先级等；两边再次一致才保存新基线。日期晚于 hard_deadline 时停止该改期并给替代方案，不能静默改硬期限。

## lark-cli 适配

使用 `+field-list` 验证真实字段及选项。子任务完成为「完成」，主任务完成为「已完成」，不能共用一份状态映射。命令参数以当前 CLI 帮助为准。

```powershell
lark-cli base +record-list --base-token <config主库> --table-id <子任务表> --format json --limit 200 --as user
lark-cli base +record-batch-update --base-token <config主库> --table-id <子任务表> --json @batch.json --as user
```

`batch.json` 在当前工作目录；payload 为 {"update_records":{"recID":{"字段名":值}}}。读取 json 的 data.fields、data.record_id_list、data.data 是位置矩阵，按位置 zip 并完整翻页。文本使用字符串；select 使用单元素数组；checkbox 使用布尔；关联主任务使用 [{"id":"recID"}]；清空可使用 null；datetime 写入使用 CLI 支持的日期时间格式并核对时区，读取可能为 ms 时间戳。不要直接把归一化字段名或 ISO 完成时间原样交给不支持它的接口。

批量响应成功不证明每条记录/字段落地，必须读回预期记录并比对。字段选项变更属额外 schema 操作，只有有授权时执行；更新选项前读全量，保留原有选项。

## 基线和并发

用 scripts/commit_state.py 将经过 receipt + 双边快照核验的结果保存到映射、基线、评论指纹。脚本用本地排他锁及临时文件替换；同时核对 state 的原始指纹，避免后提交覆盖另一会话的新状态。外部操作前仍需重新读目标并比对 precondition 的 base_hash/target_hash；锁只保护本地提交，不代表外部任务没有并发修改。

任一写入证据不完整、前置快照改变或字段读回不符时不宣称完成，不保存失败评论为已消费，也不推进该任务的后续排期。
