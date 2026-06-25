import datetime
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

import yaml


FORMAT = "paragon-items-change-package"
VERSION = 1
ITEM_TABLE = "items"
ITEM_TYPE = "Item"


@dataclass
class ImportResult:
    applied: int = 0
    already_applied: int = 0
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def export_items(project, output_path: str) -> int:
    config_root = _config_root(project)
    item_def = _item_definition(config_root, project.language.value)
    with tempfile.TemporaryDirectory() as clean_output:
        baseline = _load_data(project, config_root, clean_output)
        source = _load_data(project, config_root, project.output_path)
        package = {
            "format": FORMAT,
            "version": VERSION,
            "game": project.game.value,
            "language": project.language.value,
            "project_name": project.name,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "schema": {
                "item": item_def,
            },
            "changes": {
                "items": _diff_items(baseline, source, item_def),
            },
        }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(package, f, ensure_ascii=False, indent=2, sort_keys=True)
    return len(package["changes"]["items"])


def import_items(project, current_data, package_path: str) -> ImportResult:
    package = _read_package(package_path)
    _validate_package(project, package)

    config_root = _config_root(project)
    item_def = _item_definition(config_root, project.language.value)
    dest_rids = _item_rids_by_key(current_data)
    result = ImportResult()
    item_fields = {spec.get("id"): spec for spec in _item_fields(item_def)}
    for item_change in package["changes"]["items"]:
        _apply_item_change(
            result,
            current_data,
            item_def,
            item_fields,
            dest_rids,
            item_change,
        )
    return result


def _read_package(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        package = json.load(f)
    if not isinstance(package, dict):
        raise ValueError("Change package must be a JSON object.")
    return package


def _validate_package(project, package: dict[str, Any]) -> None:
    if package.get("format") != FORMAT:
        raise ValueError("This is not a Paragon item change package.")
    if package.get("version") != VERSION:
        raise ValueError(f"Unsupported item change package version {package.get('version')}.")
    if package.get("game") != project.game.value:
        raise ValueError(
            f"Package is for {package.get('game')}, but this project is {project.game.value}."
        )
    if package.get("language") != project.language.value:
        raise ValueError(
            "Package language does not match this project "
            f"({package.get('language')} != {project.language.value})."
        )
    if not isinstance(package.get("changes"), dict):
        raise ValueError("Change package is missing a valid changes object.")
    if not isinstance(package["changes"].get("items"), list):
        raise ValueError("Change package is missing a valid items change list.")


def _config_root(project) -> str:
    return os.path.normpath(os.path.join(os.getcwd(), "Data", project.game.value))


def _load_data(project, config_root: str, output_path: str):
    from paragon import paragon as pgn

    gd = pgn.GameData.load(
        os.path.normpath(output_path),
        os.path.normpath(project.rom_path),
        project.game.value,
        project.language.value,
        config_root,
    )
    gd.read()
    return gd


def _item_definition(config_root: str, language: str) -> dict[str, Any]:
    type_dirs = [
        os.path.join(config_root, "Types"),
        os.path.join(config_root, "Types", "Generated"),
        os.path.join(config_root, "Types", language),
    ]
    merged: dict[str, Any] = {}
    for type_dir in type_dirs:
        if not os.path.isdir(type_dir):
            continue
        for filename in os.listdir(type_dir):
            if not filename.lower().endswith((".yml", ".yaml")):
                continue
            with open(os.path.join(type_dir, filename), "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                merged.update(data)
    if ITEM_TYPE not in merged:
        raise ValueError("This game does not define an Item type.")
    return merged[ITEM_TYPE]


def _item_fields(item_def: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        spec
        for spec in item_def.get("fields", [])
        if not spec.get("skip_write")
    ]


def _item_table(gd):
    table = gd.table(ITEM_TABLE)
    if table is None:
        raise ValueError("Could not find the Items table in this project.")
    return table


def _ordered_items(gd) -> list[tuple[int, str, Any]]:
    table_rid, list_id = _item_table(gd)
    result = []
    for i in range(gd.list_size(table_rid, list_id)):
        rid = gd.list_get(table_rid, list_id, i)
        key = gd.key(rid)
        if key:
            result.append((i, key, rid))
    return result


def _item_rids_by_key(gd) -> dict[str, Any]:
    table_rid, list_id = _item_table(gd)
    result = {}
    for i in range(gd.list_size(table_rid, list_id)):
        rid = gd.list_get(table_rid, list_id, i)
        key = gd.key(rid)
        if key:
            result[key] = rid
    return result


def _diff_items(baseline, source, item_def: dict[str, Any]) -> list[dict[str, Any]]:
    base_items = _item_rids_by_key(baseline)
    changes = []
    fields = _item_fields(item_def)
    seen_keys = set()
    for index, key, rid in _ordered_items(source):
        if key in seen_keys:
            continue
        seen_keys.add(key)
        changed_fields = _diff_item_fields(
            baseline,
            source,
            base_items.get(key),
            rid,
            fields,
        )
        if not changed_fields:
            continue
        changes.append({"index": index, "iid": key, "fields": changed_fields})
    return changes


def _diff_item_fields(
    baseline,
    source,
    base_rid,
    source_rid,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    changed_fields = {}
    for spec in fields:
        field_id = spec.get("id")
        if not field_id:
            continue
        source_value = _item_field_value(source, source_rid, spec)
        base_value = (
            None if base_rid is None else _item_field_value(baseline, base_rid, spec)
        )
        if source_value != base_value:
            changed_fields[field_id] = source_value
    return changed_fields


def _item_field_value(gd, rid, spec: dict[str, Any]) -> Any:
    field_id = spec.get("id")
    field_type = spec.get("type")
    if field_type == "int":
        return gd.int(rid, field_id)
    if field_type in {"label", "message", "string"}:
        return gd.string(rid, field_id)
    if field_type == "bytes":
        value = gd.bytes(rid, field_id)
        return None if value is None else list(value)
    if field_type == "float":
        return gd.float(rid, field_id)
    if field_type == "bool":
        return gd.bool(rid, field_id)
    raise ValueError(f"Unsupported Item field type '{field_type}' for field '{field_id}'.")


def _apply_item_change(
    result: ImportResult,
    destination,
    item_def: dict[str, Any],
    item_fields: dict[str, dict[str, Any]],
    dest_rids: dict[str, Any],
    change: dict[str, Any],
) -> None:
    key = change.get("iid") if isinstance(change, dict) else None
    fields = change.get("fields") if isinstance(change, dict) else None
    if not key or not isinstance(key, str) or not isinstance(fields, dict):
        result.errors.append(f"Malformed item change {change!r}.")
        return

    if key in dest_rids:
        rid = dest_rids[key]
    else:
        table_rid, list_id = _item_table(destination)
        rid = destination.list_add(table_rid, list_id)
        _initialize_default_item(destination, rid, item_def)
        destination.set_string(rid, _item_key_field(item_def), key)
        dest_rids[key] = rid

    applied = False
    already_applied = True
    for field_id, incoming_value in fields.items():
        spec = item_fields.get(field_id)
        if spec is None:
            result.errors.append(f"Unknown Item field '{field_id}' for {key}.")
            already_applied = False
            continue
        try:
            current_value = _item_field_value(destination, rid, spec)
            normalized_value = _normalize_item_field_value(spec, incoming_value)
            if current_value == normalized_value:
                continue
            _set_item_field_value(destination, rid, spec, normalized_value)
            applied = True
            already_applied = False
        except (TypeError, ValueError) as exc:
            result.errors.append(f"Failed to apply field '{field_id}' for {key}: {exc}")
            already_applied = False

    if applied:
        result.applied += 1
    elif already_applied:
        result.already_applied += 1


def _normalize_item_field_value(spec: dict[str, Any], value: Any) -> Any:
    field_id = spec.get("id")
    field_type = spec.get("type")
    if field_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("expected an integer")
        return value
    if field_type in {"label", "message", "string"}:
        if value is not None and not isinstance(value, str):
            raise TypeError("expected a string or null")
        return value
    if field_type == "bytes":
        if not isinstance(value, list):
            raise TypeError("expected a byte array")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in value):
            raise TypeError("expected byte array values to be integers")
        if any(v < 0 or v > 0xFF for v in value):
            raise ValueError("byte array values must be between 0 and 255")
        expected_length = spec.get("length")
        if expected_length is not None and len(value) != expected_length:
            raise ValueError(
                f"expected byte array length {expected_length}, got {len(value)}"
            )
        return value
    if field_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("expected a number")
        return float(value)
    if field_type == "bool":
        if not isinstance(value, bool):
            raise TypeError("expected a boolean")
        return value
    raise ValueError(f"Unsupported Item field type '{field_type}' for field '{field_id}'.")


def _set_item_field_value(gd, rid, spec: dict[str, Any], value: Any) -> None:
    field_id = spec.get("id")
    field_type = spec.get("type")
    if field_type == "int":
        gd.set_int(rid, field_id, value)
    elif field_type in {"label", "message", "string"}:
        gd.set_string(rid, field_id, value)
    elif field_type == "bytes":
        gd.set_bytes(rid, field_id, value)
    elif field_type == "float":
        gd.set_float(rid, field_id, value)
    elif field_type == "bool":
        gd.set_bool(rid, field_id, value)
    else:
        raise ValueError(f"Unsupported Item field type '{field_type}' for field '{field_id}'.")


def _initialize_default_item(gd, rid, item_def: dict[str, Any]) -> None:
    for spec in _item_fields(item_def):
        field_id = spec.get("id")
        field_type = spec.get("type")
        if not field_id:
            continue
        if field_type in {"label", "message", "string"}:
            if gd.string(rid, field_id) is None:
                gd.set_string(rid, field_id, "")
        elif field_type == "int":
            gd.set_int(rid, field_id, 0)
        elif field_type == "float":
            gd.set_float(rid, field_id, 0.0)
        elif field_type == "bool":
            gd.set_bool(rid, field_id, False)
        elif field_type == "bytes":
            gd.set_bytes(rid, field_id, [0] * spec.get("length", 0))


def _item_key_field(item_def: dict[str, Any]) -> str:
    key_field = item_def.get("key")
    if not key_field:
        raise ValueError("Item type does not define a key field.")
    return key_field
