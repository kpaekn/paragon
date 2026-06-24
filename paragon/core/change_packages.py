import datetime
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

import yaml


FORMAT = "paragon-item-icons-change-package"
VERSION = 1
ITEM_TABLE = "items"
ITEM_TYPE = "Item"
ICON_FIELD = "icon"


@dataclass
class ImportResult:
    applied: int = 0
    already_applied: int = 0
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def export_items(project, output_path: str) -> int:
    config_root = _config_root(project)
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
            "changes": {
                "items": _diff_item_icons(baseline, source),
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
    for item_change in package["changes"]["items"]:
        _apply_icon_change(result, current_data, item_def, dest_rids, item_change)
    return result


def _read_package(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        package = json.load(f)
    if not isinstance(package, dict):
        raise ValueError("Change package must be a JSON object.")
    return package


def _validate_package(project, package: dict[str, Any]) -> None:
    if package.get("format") != FORMAT:
        raise ValueError("This is not a Paragon item icon change package.")
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


def _snapshot_item_icons(gd) -> dict[str, int]:
    return {
        key: gd.int(rid, ICON_FIELD)
        for key, rid in _item_rids_by_key(gd).items()
    }


def _ordered_item_icons(gd) -> list[tuple[int, str, int]]:
    table_rid, list_id = _item_table(gd)
    result = []
    for i in range(gd.list_size(table_rid, list_id)):
        rid = gd.list_get(table_rid, list_id, i)
        key = gd.key(rid)
        if key:
            result.append((i, key, gd.int(rid, ICON_FIELD)))
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


def _diff_item_icons(baseline, source) -> list[dict[str, Any]]:
    base_icons = _snapshot_item_icons(baseline)
    changes = []
    for index, key, icon in _ordered_item_icons(source):
        if base_icons.get(key) == icon:
            continue
        changes.append({"index": index, "iid": key, "icon": icon})
    return changes


def _apply_icon_change(
    result: ImportResult,
    destination,
    item_def: dict[str, Any],
    dest_rids: dict[str, Any],
    change: dict[str, Any],
) -> None:
    key = change.get("iid") if isinstance(change, dict) else None
    icon = change.get("icon") if isinstance(change, dict) else None
    if not key or not isinstance(key, str) or not isinstance(icon, int):
        result.errors.append(f"Malformed item icon change {change!r}.")
        return

    if key in dest_rids:
        _apply_update(result, destination, dest_rids[key], icon)
    else:
        _apply_add(result, destination, item_def, dest_rids, key, icon)


def _apply_add(
    result: ImportResult,
    destination,
    item_def: dict[str, Any],
    dest_rids: dict[str, Any],
    key: str,
    incoming_value: int,
) -> None:
    table_rid, list_id = _item_table(destination)
    rid = destination.list_add(table_rid, list_id)
    _initialize_default_item(destination, rid, item_def)
    destination.set_string(rid, _item_key_field(item_def), key)
    destination.set_int(rid, ICON_FIELD, incoming_value)
    dest_rids[key] = rid
    result.applied += 1


def _apply_update(
    result: ImportResult,
    destination,
    rid,
    incoming_value: int,
) -> None:
    destination.set_int(rid, ICON_FIELD, incoming_value)
    result.applied += 1


def _initialize_default_item(gd, rid, item_def: dict[str, Any]) -> None:
    for spec in _item_fields(item_def):
        field_id = spec.get("id")
        field_type = spec.get("type")
        if not field_id or field_id == ICON_FIELD:
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
