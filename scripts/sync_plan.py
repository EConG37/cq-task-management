#!/usr/bin/env python3
"""Offline plans and receipt verification; never calls providers or saves state."""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

PRIORITIES = {"p1", "p2", "p3", "p4"}
BASE_STATUSES = {"pending", "active", "blocked", "done", "cancelled"}
TODO_STATUSES = {"open", "done", "deleted"}
PLAN_START = "[cq-current-plan]"
PLAN_END = "[/cq-current-plan]"


def fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def source_marker(scope, action_id):
    return "[goal-flow:" + fingerprint([scope, action_id])[:32] + "]"


def valid_date(value, timestamp=False):
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError("dates must be ISO strings or null")
    if len(value) == 10 and not timestamp:
        date.fromisoformat(value)
        return
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("datetime must include a timezone")


def validate_record(record, base):
    if not isinstance(record, dict):
        raise ValueError("records must be objects")
    required = {"id", "title", "status", "planned_for", "priority", "completed_at"}
    required |= {"publish"} if base else {"description", "recurring"}
    missing = required - record.keys()
    if missing:
        raise ValueError("missing normalized fields: " + ", ".join(sorted(missing)))
    for key in ("id", "title"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError(key + " must be a nonempty string")
    if record["status"] not in (BASE_STATUSES if base else TODO_STATUSES):
        raise ValueError("unknown normalized status")
    if record["priority"] not in PRIORITIES:
        raise ValueError("priority must be p1..p4")
    bool_key = "publish" if base else "recurring"
    if not isinstance(record[bool_key], bool):
        raise ValueError(bool_key + " must be boolean")
    if not base and not isinstance(record["description"], str):
        raise ValueError("description must be a string")
    if base and record.get("todoist_id") is not None:
        if not isinstance(record["todoist_id"], str) or not record["todoist_id"].strip():
            raise ValueError("todoist_id must be a nonempty string or null")
    for key in ("main_task_id", "deliverable", "record_url", "project_id", "parent_id", "details"):
        if record.get(key) is not None and not isinstance(record[key], str):
            raise ValueError(key + " must be a string or null")
    if record["planned_for"] is not None:
        day(record["planned_for"])
    valid_date(record["completed_at"], timestamp=True)
    if base:
        if record.get("hard_deadline") is not None:
            day(record["hard_deadline"])
    elif record.get("deadline_date") is not None:
        day(record["deadline_date"])
    if record["status"] == "done" and not record["completed_at"]:
        raise ValueError("done requires actual completion timestamp")


def indexed(records, base):
    if not isinstance(records, list):
        raise ValueError("snapshots must be arrays")
    result = {}
    for record in records:
        validate_record(record, base)
        if record["id"] in result:
            raise ValueError("duplicate snapshot ID: " + record["id"])
        result[record["id"]] = record
    return result


def progress(actions):
    indexed(actions, True)
    main_tasks = defaultdict(list)
    for action in actions:
        if action.get("main_task_id"):
            main_tasks[action["main_task_id"]].append(action)
    result = []
    for main_task_id, items in sorted(main_tasks.items()):
        active = [item for item in items if item["status"] != "cancelled"]
        done = sum(item["status"] == "done" for item in active)
        result.append({
            "main_task_id": main_task_id, "active": len(active), "done": done,
            "cancelled": len(items) - len(active),
            "action_percent": round(100 * done / len(active), 1) if active else None,
            "ready_for_acceptance": bool(active) and done == len(active),
        })
    return result


def operation(kind, action, fields, target=None, current=None, marker=None):
    identity = [kind, action["id"], target, fields]
    return {
        "op_id": fingerprint(identity)[:32], "kind": kind,
        "action_id": action["id"], "target_id": target, "fields": fields,
        "precondition": {"target_hash": fingerprint(current), "base_hash": fingerprint(action)} if current is not None else {
            "base_hash": fingerprint(action), "marker_absent": marker,
        },
    }


def day(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("planned dates must be YYYY-MM-DD")
    return date.fromisoformat(value)


def execution_matches(action, task):
    return (all(action[k] == task[k] for k in ("planned_for", "priority", "completed_at"))
            and (action["status"] == "done") == (task["status"] == "done"))


def replace_current_plan(details, current_plan, legacy_plan=None):
    if not isinstance(details, str) or not isinstance(current_plan, str):
        raise ValueError("current plan requires read-back text")
    if any(marker in current_plan for marker in (PLAN_START, PLAN_END)):
        raise ValueError("reserved current-plan marker")
    lines = details.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == PLAN_START]
    ends = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == PLAN_END]
    block = PLAN_START + "\n" + current_plan.strip() + "\n" + PLAN_END if current_plan.strip() else ""
    if starts or ends:
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise ValueError("ambiguous current-plan block")
        before = "".join(lines[:starts[0]])
        inside = "".join(lines[starts[0] + 1:ends[0]])
        if "[personal-task-flow-review:" in inside:
            raise ValueError("current-plan block overlaps comment history")
        after = "".join(lines[ends[0] + 1:])
        return before + (block + "\n" if block and after else block) + after
    if legacy_plan is not None:
        if (not isinstance(legacy_plan, str) or not legacy_plan.strip()
                or "[personal-task-flow-review:" in legacy_plan):
            raise ValueError("legacy plan must be the approved leading text")
        if details == legacy_plan:
            details = ""
        elif details.startswith(legacy_plan + "\n") or details.startswith(legacy_plan + "\r\n"):
            details = details[len(legacy_plan):]
        else:
            raise ValueError("legacy plan no longer matches")
    return block + ("\n" if block and details else "") + details


def task_is_withdrawn(action, task, route):
    return (action["status"] == "cancelled" and action["planned_for"] is None
            and action["publish"] and action.get("todoist_id") == task["id"]
            and task["status"] == "open" and not task["recurring"]
            and task["planned_for"] is None and "deadline_date" in task and task["deadline_date"] is None
            and isinstance(action.get("details"), str)
            and not {PLAN_START, PLAN_END}.intersection(action["details"].splitlines())
            and execution_matches(action, task) and action["title"] == task["title"]
            and route is not None and task.get("project_id") == route["project_id"]
            and task.get("parent_id") == route["todoist_id"])


def validate_bindings(routes, mappings):
    if not isinstance(routes, dict) or not isinstance(mappings, dict):
        raise ValueError("main_task_bindings and action_mappings must be objects")
    parents = set()
    for key, route in routes.items():
        if (not isinstance(key, str) or not key or not isinstance(route, dict)
                or any(not isinstance(route.get(k), str) or not route[k] for k in ("todoist_id", "project_id"))):
            raise ValueError("each main task needs todoist_id and project_id")
        if route["todoist_id"] in parents:
            raise ValueError("duplicate main task binding")
        parents.add(route["todoist_id"])
    if any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in mappings.items()):
        raise ValueError("action mapping IDs must be nonempty strings")
    if len(set(mappings.values())) != len(mappings):
        raise ValueError("a Todoist ID cannot bind multiple actions")
    if parents.intersection(mappings.values()) or routes.keys() & mappings.keys():
        raise ValueError("main task and action bindings must be separate")


def plan_sync(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")
    scope = snapshot.get("scope")
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("a stable nonempty scope is required")
    direction = snapshot.get("direction")
    if direction not in {"publish", "pull", "reschedule", "withdraw"}:
        raise ValueError("direction must be publish, pull, reschedule or withdraw")
    authorized = snapshot.get("authorized_action_ids", [])
    if not isinstance(authorized, list) or any(not isinstance(a, str) or not a for a in authorized):
        raise ValueError("authorized_action_ids must contain explicitly authorized action IDs")
    authorized = set(authorized)
    initial = snapshot.get("accepted_initial_action_ids", [])
    if not isinstance(initial, list) or any(not isinstance(a, str) or not a for a in initial):
        raise ValueError("accepted_initial_action_ids must be an array of IDs")
    initial = set(initial)
    changes = snapshot.get("approved_changes", {})
    if not isinstance(changes, dict):
        raise ValueError("approved_changes must be an object")
    replacements = snapshot.get("replacement_sources", {})
    if not isinstance(replacements, dict) or any(
        not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not i or i == new for i in ids)
        for new, ids in replacements.items()
    ):
        raise ValueError("replacement_sources must map each new action to its old action IDs")
    distinct = snapshot.get("distinct_new_action_ids", [])
    if not isinstance(distinct, list) or any(not isinstance(i, str) or not i for i in distinct):
        raise ValueError("distinct_new_action_ids must contain explicitly approved IDs")
    if direction == "publish":
        window = snapshot.get("window", {})
        start, end = day(window.get("start")), day(window.get("end"))
        if not 0 <= (end - start).days <= 6:
            raise ValueError("new-task publication window must be 1..7 consecutive days")
    coverage = snapshot.get("coverage", {})
    if not isinstance(coverage, dict):
        raise ValueError("coverage must be an object")
    if coverage.get("base") is not True or coverage.get("todoist") is not True:
        raise ValueError("incomplete coverage: no write plan can be produced")
    actions = indexed(snapshot.get("base_actions"), True)
    tasks = indexed(snapshot.get("todoist_tasks"), False)
    if "mappings" in snapshot:
        raise ValueError("legacy mixed mappings not supported; supply action_mappings and main_task_bindings")
    mappings = snapshot.get("action_mappings", {})
    routes = snapshot.get("main_task_bindings", {})
    validate_bindings(routes, mappings)
    baselines = snapshot.get("baselines", {})
    if not isinstance(mappings, dict) or not isinstance(baselines, dict):
        raise ValueError("mappings and baselines must be objects")
    if any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in mappings.items()):
        raise ValueError("mapping IDs must be nonempty strings")
    if len(set(mappings.values())) != len(mappings):
        raise ValueError("a Todoist ID cannot bind multiple actions")
    for action_id, baseline in baselines.items():
        if not isinstance(baseline, dict) or "base" not in baseline or "todoist" not in baseline:
            raise ValueError("each baseline needs actual base and todoist records")
        validate_record(baseline["base"], True)
        validate_record(baseline["todoist"], False)
        if baseline["base"]["id"] != action_id:
            raise ValueError("baseline action ID mismatch")

    operations, conflicts, recovered, withdrawal_evidence = [], [], {}, {}

    def conflict(action_id, reason, **detail):
        conflicts.append({"action_id": action_id, "reason": reason, **detail})

    for action_id in authorized - actions.keys():
        conflict(action_id, "base_record_missing")
    bound_ids = dict(mappings)
    for action_id, action in actions.items():
        base_id = action.get("todoist_id")
        if base_id and action_id in bound_ids and bound_ids[action_id] != base_id:
            conflict(action_id, "mapping_disagrees_with_base")
            continue
        if base_id:
            bound_ids[action_id] = base_id
    reverse = defaultdict(list)
    for action_id, task_id in bound_ids.items():
        reverse[task_id].append(action_id)
    invalid_bindings = {a for owners in reverse.values() if len(owners) > 1 for a in owners}
    marker_owners = defaultdict(list)
    marker_candidates = defaultdict(list)
    for action_id in actions:
        marker = source_marker(scope, action_id)
        for task in tasks.values():
            if marker in (line.strip() for line in task["description"].splitlines()):
                marker_owners[task["id"]].append(action_id)
                marker_candidates[action_id].append(task)
    ambiguous_markers = {a for owners in marker_owners.values() if len(owners) > 1 for a in owners}
    withdrawn = {
        action_id for action_id, task_id in bound_ids.items()
        if action_id in actions and task_id in tasks and action_id not in invalid_bindings
        and action_id not in ambiguous_markers
        and [t["id"] for t in marker_candidates[action_id]] in ([], [task_id])
        and not any(c["action_id"] == action_id for c in conflicts)
        and task_is_withdrawn(actions[action_id], tasks[task_id], routes.get(actions[action_id].get("main_task_id")))
    }
    withdrawn_task_ids = {bound_ids[action_id] for action_id in withdrawn}

    for action_id, action in sorted(actions.items()):
        if action_id not in authorized:
            continue
        if any(c["action_id"] == action_id for c in conflicts):
            continue
        if action_id in invalid_bindings:
            conflict(action_id, "duplicate_binding")
            continue
        if action_id in ambiguous_markers:
            conflict(action_id, "task_has_multiple_source_markers")
            continue
        marker = source_marker(scope, action_id)
        candidates = marker_candidates[action_id]
        if len(candidates) > 1:
            conflict(action_id, "duplicate_source_marker", task_ids=[t["id"] for t in candidates])
            continue
        task_id = bound_ids.get(action_id)
        if task_id:
            task = tasks.get(task_id)
            if task is None:
                conflict(action_id, "mapped_task_missing", task_id=task_id)
                continue
            if candidates and candidates[0]["id"] != task_id:
                conflict(action_id, "marker_disagrees_with_mapping")
                continue
        elif candidates:
            task = candidates[0]
            task_id = task["id"]
            if task_id in reverse and action_id not in reverse[task_id]:
                conflict(action_id, "marker_task_already_bound")
                continue
        else:
            task = None

        route = routes.get(action.get("main_task_id"))
        if route is None:
            conflict(action_id, "main_task_binding_required")
            continue
        if task_id in {r["todoist_id"] for r in routes.values()}:
            conflict(action_id, "action_bound_to_main_task")
            continue
        if direction in {"publish", "pull"} and action_id in replacements:
            waiting = set(replacements.get(action_id, [])) - withdrawn
            if waiting:
                conflict(action_id, "replacement_requires_withdrawal", old_action_ids=sorted(waiting))
                continue
            withdrawal_evidence[action_id] = {
                old_id: {"base_hash": fingerprint(actions[old_id]),
                         "todoist_id": bound_ids[old_id], "todoist_hash": fingerprint(tasks[bound_ids[old_id]])}
                for old_id in replacements[action_id]
            }
        if task is None:
            if direction != "publish" or action["status"] == "cancelled":
                conflict(action_id, "unbound_action" if direction != "publish" else "cancelled_action_cannot_be_published")
                continue
            if action["publish"]:
                conflict(action_id, "published_binding_unresolved")
                continue
            if action["status"] == "done":
                conflict(action_id, "completed_action_cannot_be_published")
                continue
            if action["planned_for"] is None:
                conflict(action_id, "planned_date_required")
                continue
            if not start <= day(action["planned_for"]) <= end:
                conflict(action_id, "outside_publication_window")
                continue
            if action.get("hard_deadline") and day(action["planned_for"]) > day(action["hard_deadline"]):
                conflict(action_id, "hard_deadline_exceeded")
                continue
            same_title = [
                t["id"] for t in tasks.values()
                if t["status"] == "open" and t["id"] not in withdrawn_task_ids
                and t.get("project_id") == route["project_id"] and t.get("parent_id") == route["todoist_id"]
                and " ".join(t["title"].split()).casefold() == " ".join(action["title"].split()).casefold()
            ]
            if same_title and action_id not in distinct:
                conflict(action_id, "possible_duplicate_open_task", task_ids=sorted(same_title))
                continue
            notes = [str(action.get("deliverable") or "").strip()]
            if action.get("hard_deadline"):
                notes.append("Hard deadline: " + action["hard_deadline"])
            notes.extend([str(action.get("record_url") or "").strip(), marker])
            fields = {
                "title": action["title"], "description": "\n".join(n for n in notes if n),
                "priority": action["priority"], "planned_for": action["planned_for"],
                "project_id": route["project_id"], "parent_id": route["todoist_id"],
            }
            if action.get("hard_deadline"):
                fields["deadline_date"] = action["hard_deadline"]
            create = operation("todoist.create", action, fields, marker=marker)
            if action_id in withdrawal_evidence:
                create["precondition"]["withdrawn_sources"] = withdrawal_evidence[action_id]
            operations.append(create)
            continue
        if task["status"] == "deleted":
            conflict(action_id, "todoist_deleted_requires_decision")
            continue
        if action["status"] == "cancelled" and direction != "withdraw":
            conflict(action_id, "withdrawal_requires_decision")
            continue
        if task["recurring"]:
            conflict(action_id, "recurring_binding_not_supported")
            continue
        if task.get("project_id") != route["project_id"] or task.get("parent_id") != route["todoist_id"]:
            conflict(action_id, "task_route_changed_requires_decision")
            continue
        if not mappings.get(action_id):
            recovered[action_id] = task_id
        if direction == "publish":
            # A retry must reuse an existing task, even if the Base write failed.
            continue

        if direction == "withdraw":
            if snapshot.get("facts_synced") is not True:
                conflict(action_id, "facts_and_reviews_must_be_synced_first")
                continue
            if (task["status"] != "open" or action["status"] == "done" or task["completed_at"]
                    or action["completed_at"] or task["title"] != action["title"]
                    or task["priority"] != action["priority"]):
                conflict(action_id, "withdrawal_requires_matching_open_task")
                continue
            if "deadline_date" not in task:
                conflict(action_id, "withdrawal_requires_deadline_readback")
                continue
            if not action["publish"] or action.get("todoist_id") != task_id:
                conflict(action_id, "withdrawal_requires_verified_binding")
                continue
            wanted = changes.get(action_id, {})
            if not isinstance(wanted, dict) or set(wanted) - {"legacy_plan"}:
                raise ValueError("withdraw accepts only the approved legacy plan text")
            if action_id in withdrawn and not wanted:
                continue
            task_fields = {k: None for k in ("planned_for", "deadline_date") if task[k] is not None}
            base_fields = {k: v for k, v in {"status": "cancelled", "planned_for": None}.items() if action[k] != v}
            current_plan = ""
        else:
            current_plan = None

        baseline = baselines.get(action_id)
        if baseline and baseline["todoist"]["id"] != task_id:
            conflict(action_id, "baseline_task_id_mismatch")
            continue
        if direction != "withdraw" and not baseline and action_id not in initial and not execution_matches(action, task):
            conflict(action_id, "initial_execution_mismatch")
            continue

        if direction == "reschedule":
            if snapshot.get("facts_synced") is not True:
                conflict(action_id, "facts_and_reviews_must_be_synced_first")
                continue
            if task["status"] == "done":
                conflict(action_id, "completed_task_cannot_be_rescheduled")
                continue
            wanted = changes.get(action_id)
            if (not isinstance(wanted, dict) or not wanted
                    or set(wanted) - {"planned_for", "priority", "title", "current_plan", "legacy_plan"}
                    or ("legacy_plan" in wanted and "current_plan" not in wanted)):
                conflict(action_id, "explicit_schedule_changes_required")
                continue
            if "planned_for" in wanted:
                when = day(wanted["planned_for"])
                if action.get("hard_deadline") and when > day(action["hard_deadline"]):
                    conflict(action_id, "hard_deadline_exceeded")
                    continue
            if "priority" in wanted and wanted["priority"] not in PRIORITIES:
                raise ValueError("schedule priority must be p1..p4")
            if "title" in wanted and (not isinstance(wanted["title"], str) or not wanted["title"].strip()):
                raise ValueError("schedule title must be nonempty")
            if "current_plan" in wanted and not isinstance(wanted["current_plan"], str):
                raise ValueError("current_plan must be a string")
            current_plan = wanted.get("current_plan")
            execution = {k: wanted[k] for k in ("planned_for", "priority", "title") if k in wanted}
            if (current_plan is None and PLAN_START in (action.get("details") or "").splitlines()
                    and any(k in execution and execution[k] != action[k] for k in ("planned_for", "title"))):
                conflict(action_id, "current_plan_review_required")
                continue
            task_fields = {k: v for k, v in execution.items() if task.get(k) != v}
            base_fields = {k: v for k, v in execution.items() if action.get(k) != v}
        if direction in {"reschedule", "withdraw"}:
            if current_plan is not None:
                if snapshot.get("feedback_field_verified") is not True:
                    conflict(action_id, "verified_details_field_required")
                    continue
                wanted = changes.get(action_id, {})
                if not isinstance(wanted, dict):
                    raise ValueError("approved action changes must be an object")
                try:
                    details = replace_current_plan(action.get("details"), current_plan, wanted.get("legacy_plan"))
                except ValueError:
                    conflict(action_id, "current_plan_text_requires_review")
                    continue
                if details != action["details"]:
                    base_fields["details"] = details
            update = None
            if task_fields:
                update = operation("todoist.update", action, task_fields, task_id, task)
                operations.append(update)
            if base_fields:
                write = operation("base.update", action, base_fields, action_id, action)
                if update:
                    write["depends_on"] = [update["op_id"]]
                write["precondition"]["todoist_hash"] = fingerprint(task)
                operations.append(write)
            continue

        patches = {"planned_for": task["planned_for"], "priority": task["priority"]}
        if task["status"] == "done":
            patches.update(status="done", completed_at=task["completed_at"])
        else:
            patches["completed_at"] = None
            if action["status"] == "done":
                patches["status"] = "active"
        if baseline:
            old = baseline["base"]
            changed = []
            for key in ("planned_for", "priority", "completed_at"):
                if action[key] != old[key] and action[key] != patches[key]:
                    changed.append(key)
            if (action["status"] == "done") != (old["status"] == "done"):
                if (action["status"] == "done") != (task["status"] == "done"):
                    changed.append("status")
            if changed:
                conflict(action_id, "base_execution_fields_edited", fields=changed)
                continue
        if action["title"] != task["title"]:
            conflict(action_id, "title_change_requires_decision")
            continue
        patches["todoist_id"] = task_id
        patches["publish"] = True
        fields = {k: v for k, v in patches.items() if action.get(k) != v}
        if fields:
            write = operation("base.update", action, fields, action_id, action)
            write["precondition"]["todoist_hash"] = fingerprint(task)
            operations.append(write)

    eligible = authorized - {c["action_id"] for c in conflicts}
    return {
        "schema_version": "2.0", "scope": scope, "direction": direction, "operations": operations,
        "conflicts": conflicts, "recovered_mappings": {k: v for k, v in recovered.items() if not any(c['action_id'] == k for c in conflicts)},
        "progress": progress(list(actions.values())),
        "state_hashes": snapshot.get("state_hashes", {}),
        "action_ids": sorted(eligible),
        "withdrawn_sources": {k: v for k, v in withdrawal_evidence.items() if k in eligible},
    }


def verify_receipts(plan, payload):
    operations = plan.get("operations", [])
    receipts = payload.get("receipts", [])
    if not isinstance(receipts, list):
        raise ValueError("receipts must be an array")
    op_ids = [op["op_id"] for op in operations]
    if len(set(op_ids)) != len(op_ids):
        raise ValueError("duplicate plan operation ID")
    grouped = defaultdict(list)
    failures = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise ValueError("receipt must be an object")
        grouped[receipt.get("op_id")].append(receipt)
        if receipt.get("op_id") not in op_ids:
            failures.append({"op_id": receipt.get("op_id"), "reason": "unknown_receipt"})
    verified, mapping_updates = [], {}
    seen_created_ids = set()
    for op in operations:
        items = grouped.get(op["op_id"], [])
        reason = None
        observed = {}
        if any(dep not in verified for dep in op.get("depends_on", [])):
            reason = "dependency_not_verified"
        elif len(items) != 1:
            reason = "missing_or_duplicate_receipt"
        elif items[0].get("read_back") is not True:
            reason = "no_read_back"
        elif not isinstance(items[0].get("observed"), dict):
            reason = "invalid_observation"
        else:
            observed = items[0]["observed"]
            if not isinstance(observed.get("id"), str) or not observed["id"].strip():
                reason = "missing_observed_id"
            elif op["target_id"] is not None and observed["id"] != op["target_id"]:
                reason = "wrong_target"
            elif any(k not in observed or observed[k] != v for k, v in op["fields"].items()):
                reason = "fields_mismatch"
            elif op["kind"] == "todoist.create" and observed["id"] in seen_created_ids:
                reason = "duplicate_created_id"
        if reason:
            failures.append({"op_id": op["op_id"], "reason": reason})
            continue
        verified.append(op["op_id"])
        if op["kind"] == "todoist.create":
            seen_created_ids.add(observed["id"])
            mapping_updates[op["action_id"]] = observed["id"]
        elif op["kind"] == "base.update" and "todoist_id" in op["fields"]:
            mapping_updates[op["action_id"]] = op["fields"]["todoist_id"]
    return {"ok": not failures, "verified": verified, "failures": failures, "mapping_updates": mapping_updates}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("plan", "progress"):
        cmd = sub.add_parser(mode)
        cmd.add_argument("--input", required=True)
        cmd.add_argument("--output")
    cmd = sub.add_parser("verify")
    cmd.add_argument("--plan", required=True)
    cmd.add_argument("--receipts", required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "verify":
            result = verify_receipts(load_json(args.plan), load_json(args.receipts))
        elif args.mode == "progress":
            result = {"progress": progress(load_json(args.input)["base_actions"])}
        else:
            result = plan_sync(load_json(args.input))
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if getattr(args, "output", None):
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 1 if args.mode == "verify" and not result["ok"] else 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
