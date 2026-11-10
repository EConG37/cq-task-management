# 离线脚本的数据约定

脚本只处理本地快照与计划，不调用飞书/Todoist。由 Agent 读取、归一化、确认范围、执行外部工具及读回。不要把计划中的归一化字段直接当工具参数。审批 ID 列表来自当前真实授权，不是从 publish 标记推导。

## 状态与归一化

state 三个文件均为 schema_version=2.0、scopes[scope]：mappings 下为 {main_tasks:{rec:{todoist_id,project_id}},actions:{rec:taskId}}；baselines 下为 {actionId:{base:record,todoist:record}}；reviews 下为 {taskId:commentId 键对应的指纹记录}，准确的键由 comment_key() 生成。

Base 子任务归一化为 id/title/main_task_id/status/publish/todoist_id/planned_for/priority/completed_at/details；Todoist 为 id/title/status/planned_for/priority/completed_at/description/recurring/project_id/parent_id。两个 record 的 id 是各自平台的 ID。状态 Base 使用 pending/active/blocked/done/cancelled，Todoist 使用 open/done/deleted。planned_for 为 YYYY-MM-DD 或 null，completed_at 为带时区 ISO 或 null；done 必须有实际完成时间。recurring 为布尔，有循环规则字符串就归一化为 true。

Base 的 details 是现场读取的完整「任务详情」文本。主任务关联必须唯一，缺失/多个关联待核对，不能选第一个猜。原始状态「补位/未完成」等以现有含义映射到开放状态，同时保留原始快照信息供用户核对。

Todoist 写入转换：title→content，planned_for→dueString，project_id→projectId，parent_id→parentId，deadline_date→deadlineDate；读取反向转换 content/dueDate/checked/completedAt/projectId/parentId。其他 Base 字段按 config 映射及 CLI CellValue 规则编码。Base completed_at 和 Todoist completedAt 统一成同一带时区 ISO 表示，避免等价时间被判差异。

## 同步计划

```json
{
  "scope": "configured-scope",
  "direction": "publish",
  "coverage": {"base": true, "todoist": true},
  "window": {"start": "2026-10-14", "end": "2026-10-18"},
  "authorized_action_ids": ["rec-child"],
  "main_task_bindings": {"rec-main": {"todoist_id": "parent-task", "project_id": "todoist-project"}},
  "action_mappings": {},
  "baselines": {},
  "base_actions": [{"id":"rec-child","title":"确认过的工作","main_task_id":"rec-main","status":"pending","publish":false,"todoist_id":null,"planned_for":"2026-10-15","priority":"p2","completed_at":null,"details":"原有详情"}],
  "todoist_tasks": [],
  "state_hashes": {}
}
```

coverage=true 仅在相关查询完整翻页、绑定 ID 单独查过、活动/完成数据纳入后设置；按需快照可只包含此次相关子任务，但查来源标记需要覆盖可能创建过的任务。上述 ID 为接口形状示例，操作时从 state/live 读取真实值。

运行 `python scripts/sync_plan.py plan --input snapshot.json --output plan.json`。

- publish：只创建 authorized_action_ids 中、未发布且无绑定/来源标记候选、日期落在 1~7 天窗口内的任务；标记或绑定找回的任务输出 recovered_mappings，不重建。恢复后改用 pull 回写 publish/ID 并核验。已完成/取消/超硬期限的新任务不发布。
- pull：只为授权子任务生成 Base 回写。缺失基线且执行值不同报 initial_execution_mismatch；用户已决定接管值后可在 accepted_initial_action_ids 明确列出对应 ID。一致初始读回无需重新确认，可通过无操作计划 commit 保存基线。
- reschedule：facts_synced=true 且刚读回执行事实和评价后，approved_changes={actionId:{planned_for,priority,title,current_plan,legacy_plan}} 只填获授权的字段。仍使用 authorized_action_ids，复用原 ID；日期不能越过硬期限。有当前计划区时，改日期或标题必须同时提供核对后的 current_plan。传入 current_plan 时需要 feedback_field_verified=true 和完整 details 文本，空字符串清除当前计划区。legacy_plan 是待移除的旧版详情前缀原文，只用于未分区的详情迁移；精确匹配失败进入核对。
- withdraw：authorized_action_ids 只列明确需要撤出排期的旧项。要求 facts_synced=true、完整已核对的绑定，以及待更新时的 feedback_field_verified=true 和完整 details（空字段归一为 ""）。Todoist 的 deadline_date 必须从现场读取为 YYYY-MM-DD 或 null，缺字段不能视为空。按计划对原 Todoist 任务清除日期与截止日期，再读回并更新原 Base 记录的状态、日期及当前计划。approved_changes 可为旧项提供精确 legacy_plan。读回确认撤出后保存旧绑定，重试按最新快照只补未完成步骤。
- 替代项：publish 或后续恢复的 pull 提供 replacement_sources={新Base记录ID:[旧Base记录ID,...]}，只按用户已确认的替换关系填写并随 outbox 保留。旧项须有真实 Base 与 Todoist 快照、Base 已取消、计划日期为空、Todoist 已清日期及截止日期、飞书当前计划区已撤下。使用计划中的 withdrawn_sources 再次核对两边旧项；同父任务有同名开放任务时停止创建，只有确认是不同工作的具体新 ID 才能列进 distinct_new_action_ids。该例外不跳过替换前置检查。

操作前重新读两个平台目标，比较 precondition.base_hash/target_hash；有 depends_on 的 Base 更新只在 Todoist 更新读回后执行，todoist_hash 在无依赖时与原快照比对，有依赖时与已核验更新后的预期快照比对。期间发生无关变化则重新读取/生成方案，在原授权仍适用时继续，不把并发变化覆盖掉。

发布创建的 operation 只涵盖 Todoist。创建读回后还需 Agent 回写 Base publish/ID/日期，并最终双边读回，不能以 verify receipt 成功作为整次发布完成。

## 评论回写计划

在已读回执行事实的快照中增加：coverage.comments=true、facts_synced=true、feedback_field_verified=true、todoist_user_id、comments、processed_comments、interpretations。comments 为 {id,task_id,text,posted_at,author_id} 数组，对相关任务读取完整评论历史；processed_comments 从 reviews.scopes[scope] 读取。

interpretations 使用 taskId:commentId 键，值为 {status:"active",next_action:"继续后半段",proposed_date:"2026-10-16"}。由 Agent 根据原文理解，不用关键词脚本把“没完成”误判完成。未知状态为 unknown，建议日期可省略；评论本身不授予改期权限。

运行 `python scripts/review_plan.py --input snapshot.json --output review-plan.json`。它只追加评价、更新开放状态、给出 proposed_adjustments；不会勾完成、取消或自动改期。没有新评论时不改状态。每条操作仍有前置快照，执行前复核源评论指纹及任务状态。

## 读回验证及本地提交

执行外部步骤后，receipts={receipts:[{op_id,read_back:true,observed:{id,...归一化操作fields}}]}。observed 必须来自真实读回，不能复制计划冒充。按 operations/depends_on 顺序核验；独立成功项可摘出为子计划提交，失败项及其评价不标已消费。

post-snapshot 使用相同 scope、完整覆盖说明和最新 base_actions/todoist_tasks；涉及评价还要重新读取 comments、coverage.comments=true。为防并发，计划的 state_hashes 必须在准备时填入三个完整 JSON 文件的 fingerprint()，而不是只哈希 scope 切片。

```powershell
python scripts/sync_plan.py verify --plan plan.json --receipts receipts.json
python scripts/commit_state.py --plan plan.json --receipts receipts.json --snapshot post-snapshot.json --state-dir state
python scripts/validate_config.py state/config.json
python -m unittest discover -s scripts -p test_*.py
```

commit_state 只在 receipt 全部核验、最终双边快照一致时写入映射/基线/评价指纹。评价来源被编辑或 state 哈希变化时不覆盖。临时文件与排他锁保护本地提交；state/outbox/state-commit-* 日志支持同一事务崩溃恢复。原 outbox 发布历史全部保留，不当新操作重放。
