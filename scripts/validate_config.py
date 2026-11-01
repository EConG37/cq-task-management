#!/usr/bin/env python3
"""Validate non-secret configuration, not provider connectivity or permissions."""
import argparse
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CAPABILITIES = {"base_read", "base_write", "okr_read", "okr_write", "todoist_read", "todoist_write"}
LAYERS = {"base", "okr", "todoist", "calendar"}
BASE_FIELDS = {"title", "main_task_id", "status", "completed_at"}
ACTION_FIELDS = BASE_FIELDS | {"publish", "todoist_id", "planned_for", "priority"}
SYNC_FIELDS = {"title", "todoist_id", "planned_for", "priority", "status", "completed_at"}
SECRET_KEYS = {"token", "accesstoken", "refreshtoken", "apikey", "apitoken", "password", "appsecret", "oauthtoken", "todoistapikey"}


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate(config):
    errors = []
    if not isinstance(config, dict):
        return ["configuration must be an object"]

    def check_secrets(value, path="config"):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower().replace("_", "").replace("-", "")
                if normalized in SECRET_KEYS:
                    errors.append(path + "." + key + ": credentials must stay in the connector")
                check_secrets(child, path + "." + str(key))
        elif isinstance(value, list):
            for child in value:
                check_secrets(child, path)

    check_secrets(config)
    version = config.get("schema_version")
    if version != "2.0":
        errors.append("schema_version must be 2.0 (main task/action model)")
    layers = {"base": True, "okr": True, "todoist": True, "calendar": False}
    if version == "2.0":
        supplied_layers = config.get("layers")
        if not isinstance(supplied_layers, dict):
            errors.append("layers must be an object with explicit enable flags")
            supplied_layers = {}
        if set(supplied_layers) - LAYERS:
            errors.append("layers contains unsupported layers")
        for key in LAYERS:
            if not isinstance(supplied_layers.get(key), bool):
                errors.append("layers." + key + " must be boolean")
        layers = {key: supplied_layers.get(key) is True for key in LAYERS}
    if not isinstance(config.get("configured"), bool):
        errors.append("configured must be boolean")
    if not nonempty(config.get("timezone")):
        errors.append("timezone must be an IANA timezone name")
    else:
        try:
            ZoneInfo(config["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            errors.append("timezone is unknown or IANA timezone data is unavailable")
    containers = {}
    for key in ("feishu", "todoist", "capabilities", "sync"):
        value = config.get(key)
        if not isinstance(value, dict):
            errors.append(key + " must be an object")
            value = {}
        containers[key] = value
    caps, sync = containers["capabilities"], containers["sync"]
    required_caps = CAPABILITIES | {"calendar_read", "calendar_write"}
    for key in required_caps:
        if not isinstance(caps.get(key), bool):
            errors.append("capabilities." + key + " must be boolean")
    if sync.get("mode") not in {"on_demand", "scheduled"}:
        errors.append("sync.mode must be on_demand or scheduled")
    if not isinstance(sync.get("approved"), bool):
        errors.append("sync.approved must be boolean")
    fields = sync.get("approved_fields")
    if not isinstance(fields, list) or any(not isinstance(f, str) or f not in SYNC_FIELDS for f in fields):
        errors.append("sync.approved_fields contains unsupported fields")
    if not isinstance(sync.get("automation_ids"), list) or any(not nonempty(i) for i in sync.get("automation_ids", [])):
        errors.append("sync.automation_ids must be a list of real nonempty IDs")
    if config.get("configured") is True:
        if not any(layers.values()):
            errors.append("configured system requires at least one enabled layer")
        if not nonempty(config.get("scope")):
            errors.append("configured system requires a stable scope")
        feishu, todoist = containers["feishu"], containers["todoist"]
        needed_ids = []
        if layers["base"]:
            needed_ids.append("base_token")
        if layers["okr"]:
            needed_ids.extend(("okr_owner_id", "okr_cycle_id"))
        if layers["calendar"]:
            needed_ids.append("calendar_id")
        for key in needed_ids:
            if not nonempty(feishu.get(key)):
                errors.append("feishu." + key + " is required")
        tables = feishu.get("tables", {})
        if not isinstance(tables, dict):
            errors.append("feishu.tables must be an object")
            tables = {}
        for key in (("main_tasks", "actions") if layers["base"] else ()):
            if not nonempty(tables.get(key)):
                errors.append("feishu.tables." + key + " is required")
        mappings = feishu.get("fields", {})
        if not isinstance(mappings, dict):
            errors.append("feishu.fields must be an object")
            mappings = {}
        action_fields = mappings.get("actions", {})
        if not isinstance(action_fields, dict):
            action_fields = {}
        needed_action_fields = (ACTION_FIELDS if layers["todoist"] else BASE_FIELDS) if layers["base"] else set()
        for key in needed_action_fields:
            if not nonempty(action_fields.get(key)):
                errors.append("feishu.fields.actions." + key + " is required")
        selected_fields = [action_fields.get(key) for key in needed_action_fields if nonempty(action_fields.get(key))]
        if len(selected_fields) != len(set(selected_fields)):
            errors.append("action field mappings must be distinct")
        for key, expected in (("status_values", {"pending", "active", "blocked", "done", "cancelled"}), ("priority_values", {"p1", "p2", "p3", "p4"})):
            if not layers["base"] or (key == "priority_values" and not layers["todoist"]):
                continue
            values = feishu.get(key, {})
            if not isinstance(values, dict) or any(not nonempty(values.get(k)) for k in expected):
                errors.append("feishu." + key + " requires all normalized value mappings")
            elif len({values[k] for k in expected}) != len(expected):
                errors.append("feishu." + key + " must not merge distinct states/priorities")
        for key in (("user_id",) if layers["todoist"] else ()):
            if not nonempty(todoist.get(key)):
                errors.append("todoist." + key + " is required")
        for key in (layer + "_read" for layer in LAYERS if layers[layer]):
            if caps.get(key) is not True:
                errors.append("configured system requires " + key)
        if layers['base']:
            main_fields = mappings.get('main_tasks', {})
            for key in ('title', 'status', 'completed_at', 'acceptance'):
                if not isinstance(main_fields, dict) or not nonempty(main_fields.get(key)):
                    errors.append('feishu.fields.main_tasks.' + key + ' is required')
            main_status = feishu.get('main_status_values', {})
            if not isinstance(main_status, dict) or any(not nonempty(main_status.get(k)) for k in ('pending', 'active', 'blocked', 'done', 'cancelled')):
                errors.append('main task status mapping is required separately from action statuses')
        if layers['todoist']:
            storage = config.get('review', {}).get('storage', {})
            if not isinstance(storage, dict) or storage.get('mode') != 'append_to_text' or not nonempty(storage.get('field_name')) or not isinstance(storage.get('verified'), bool):
                errors.append('review storage requires an existing text field and verification flag')
            elif storage['verified'] and not nonempty(storage.get('field_id')):
                errors.append('verified review field requires its actual field ID')
    if sync.get("approved") is True:
        if not (layers["base"] and layers["todoist"]):
            errors.append("two-way sync requires enabled base and todoist layers")
        if config.get("configured") is not True:
            errors.append("sync approval requires configured resources")
        if not fields:
            errors.append("sync approval requires an explicit field scope")
        for key in ("base_write", "todoist_write"):
            if caps.get(key) is not True:
                errors.append("approved two-way sync requires " + key)
    if sync.get("mode") == "scheduled":
        if sync.get("approved") is not True or not nonempty(sync.get("runner")) or not sync.get("automation_ids"):
            errors.append("scheduled sync requires approval, a runner and automation IDs")
    return errors


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    args = parser.parse_args(argv)
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        errors = validate(config)
        result = {"ok": not errors, "configured": config.get("configured") if isinstance(config, dict) else None, "errors": errors}
    except (OSError, ValueError, TypeError) as exc:
        result = {"ok": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
