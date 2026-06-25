import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from paragon.core import change_packages


ITEM_DEF = {
    "size": 104,
    "key": "iid",
    "display": "name",
    "icon": "item",
    "index": "id",
    "fields": [
        {"id": "label", "type": "label"},
        {"id": "iid", "type": "string"},
        {"id": "icon", "type": "int"},
        {"id": "mt", "type": "int"},
        {"id": "bonuses", "type": "bytes", "length": 8},
        {"id": "enabled", "type": "bool"},
        {"id": "weight", "type": "float"},
    ],
}


@dataclass
class FakeRid:
    key: str


class FakeGameData:
    def __init__(self, items):
        self.rids = [FakeRid(item["key"]) for item in items]
        self.items_by_rid = {
            id(rid): {"rid": rid, "fields": item["fields"]}
            for item, rid in zip(items, self.rids)
        }
        self.items_by_key = {}
        for item, rid in zip(items, self.rids):
            self.items_by_key.setdefault(item["key"], {"rid": rid, "fields": item["fields"]})

    def table(self, table_id):
        if table_id == change_packages.ITEM_TABLE:
            return "table", "items"
        return None

    def list_size(self, _rid, _id):
        return len(self.rids)

    def list_get(self, _rid, _id, index):
        return self.rids[index]

    def list_add(self, _rid, _id):
        rid = FakeRid(f"__new_{len(self.rids)}")
        self.rids.append(rid)
        record = {"rid": rid, "fields": {}}
        self.items_by_rid[id(rid)] = record
        self.items_by_key[rid.key] = record
        return rid

    def key(self, rid):
        return rid.key

    def _fields(self, rid):
        return self.items_by_rid[id(rid)]["fields"]

    def int(self, rid, field_id):
        return self._fields(rid).get(field_id)

    def set_int(self, rid, field_id, value):
        self._fields(rid)[field_id] = value

    def string(self, rid, field_id):
        return self._fields(rid).get(field_id)

    def set_string(self, rid, field_id, value):
        self._fields(rid)[field_id] = value
        if field_id == "iid":
            old_key = rid.key
            rid.key = value
            record = self.items_by_rid[id(rid)]
            if self.items_by_key.get(old_key) is record:
                self.items_by_key.pop(old_key)
            self.items_by_key[value] = record

    def bytes(self, rid, field_id):
        return self._fields(rid).get(field_id)

    def set_bytes(self, rid, field_id, value):
        self._fields(rid)[field_id] = value

    def bool(self, rid, field_id):
        return self._fields(rid).get(field_id)

    def set_bool(self, rid, field_id, value):
        self._fields(rid)[field_id] = value

    def float(self, rid, field_id):
        return self._fields(rid).get(field_id)

    def set_float(self, rid, field_id, value):
        self._fields(rid)[field_id] = value


def _item(key, **fields):
    defaults = {
        "label": key,
        "iid": key,
        "icon": 1,
        "mt": 5,
        "bonuses": [0, 0, 0, 0, 0, 0, 0, 0],
        "enabled": True,
        "weight": 1.5,
    }
    defaults.update(fields)
    return {"key": key, "fields": defaults}


class ChangePackageTests(unittest.TestCase):
    def test_diff_items_exports_only_changed_fields(self):
        baseline = FakeGameData(
            [
                _item("IID_A"),
                _item("IID_B", bonuses=[0, 0, 0, 0, 0, 0, 0, 0]),
            ]
        )
        source = FakeGameData(
            [
                _item("IID_A"),
                _item("IID_B", icon=9, bonuses=[1, 0, 0, 0, 0, 0, 0, 0]),
            ]
        )

        changes = change_packages._diff_items(baseline, source, ITEM_DEF)

        self.assertEqual(
            changes,
            [
                {
                    "index": 1,
                    "iid": "IID_B",
                    "fields": {
                        "icon": 9,
                        "bonuses": [1, 0, 0, 0, 0, 0, 0, 0],
                    },
                }
            ],
        )

    def test_diff_items_exports_new_items_as_changed_fields(self):
        baseline = FakeGameData([_item("IID_A")])
        source = FakeGameData([_item("IID_A"), _item("IID_NEW", mt=8)])

        changes = change_packages._diff_items(baseline, source, ITEM_DEF)

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["index"], 1)
        self.assertEqual(changes[0]["iid"], "IID_NEW")
        self.assertEqual(changes[0]["fields"]["iid"], "IID_NEW")
        self.assertEqual(changes[0]["fields"]["mt"], 8)

    def test_diff_items_keeps_first_duplicate_source_iid(self):
        baseline = FakeGameData([_item("IID_A")])
        source = FakeGameData(
            [
                _item("IID_A", icon=2),
                _item("IID_DUP", icon=3),
                _item("IID_DUP", icon=4),
            ]
        )

        changes = change_packages._diff_items(baseline, source, ITEM_DEF)

        self.assertEqual(
            changes,
            [
                {
                    "index": 0,
                    "iid": "IID_A",
                    "fields": {"icon": 2},
                },
                {
                    "index": 1,
                    "iid": "IID_DUP",
                    "fields": {
                        "label": "IID_DUP",
                        "iid": "IID_DUP",
                        "icon": 3,
                        "mt": 5,
                        "bonuses": [0, 0, 0, 0, 0, 0, 0, 0],
                        "enabled": True,
                        "weight": 1.5,
                    },
                }
            ],
        )

    def test_export_items_includes_schema(self):
        project = SimpleNamespace(
            game=SimpleNamespace(value="FE14"),
            language=SimpleNamespace(value="English"),
            name="Test Project",
            output_path="/project/output",
            rom_path="/project/rom",
        )
        baseline = FakeGameData([_item("IID_A")])
        source = FakeGameData([_item("IID_A", mt=12)])

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "items.json"
            with mock.patch.object(change_packages, "_item_definition", return_value=ITEM_DEF):
                with mock.patch.object(
                    change_packages, "_load_data", side_effect=[baseline, source]
                ):
                    count = change_packages.export_items(project, str(output_path))

            package = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(count, 1)
        self.assertEqual(package["format"], change_packages.FORMAT)
        self.assertEqual(package["schema"]["item"], ITEM_DEF)
        self.assertEqual(package["changes"]["items"][0]["fields"], {"mt": 12})

    def test_new_export_format_import_updates_changed_fields(self):
        project = SimpleNamespace(
            game=SimpleNamespace(value="FE14"),
            language=SimpleNamespace(value="English"),
        )
        package = {
            "format": change_packages.FORMAT,
            "version": change_packages.VERSION,
            "game": "FE14",
            "language": "English",
            "changes": {
                "items": [
                    {
                        "index": 0,
                        "iid": "IID_A",
                        "fields": {
                            "mt": 12,
                            "bonuses": [1, 0, 0, 0, 0, 0, 0, 0],
                        },
                    }
                ]
            },
        }
        data = FakeGameData([_item("IID_A")])

        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = Path(temp_dir) / "items.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            with mock.patch.object(change_packages, "_item_definition", return_value=ITEM_DEF):
                result = change_packages.import_items(project, data, str(package_path))

        rid = data.items_by_key["IID_A"]["rid"]
        self.assertEqual(result.applied, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(data.int(rid, "mt"), 12)
        self.assertEqual(data.bytes(rid, "bonuses"), [1, 0, 0, 0, 0, 0, 0, 0])

    def test_new_export_format_import_adds_missing_item(self):
        project = SimpleNamespace(
            game=SimpleNamespace(value="FE14"),
            language=SimpleNamespace(value="English"),
        )
        package = {
            "format": change_packages.FORMAT,
            "version": change_packages.VERSION,
            "game": "FE14",
            "language": "English",
            "changes": {
                "items": [
                    {
                        "index": 1,
                        "iid": "IID_NEW",
                        "fields": {
                            "iid": "IID_NEW",
                            "icon": 7,
                            "enabled": False,
                            "weight": 2.5,
                        },
                    }
                ]
            },
        }
        data = FakeGameData([_item("IID_A")])

        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = Path(temp_dir) / "items.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            with mock.patch.object(change_packages, "_item_definition", return_value=ITEM_DEF):
                result = change_packages.import_items(project, data, str(package_path))

        rid = data.items_by_key["IID_NEW"]["rid"]
        self.assertEqual(result.applied, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(data.string(rid, "iid"), "IID_NEW")
        self.assertEqual(data.int(rid, "icon"), 7)
        self.assertEqual(data.bool(rid, "enabled"), False)
        self.assertEqual(data.float(rid, "weight"), 2.5)

    def test_legacy_icon_format_import_is_rejected(self):
        project = SimpleNamespace(
            game=SimpleNamespace(value="FE14"),
            language=SimpleNamespace(value="English"),
        )
        package = {
            "format": "paragon-item-icons-change-package",
            "version": change_packages.VERSION,
            "game": "FE14",
            "language": "English",
            "changes": {"items": [{"index": 0, "iid": "IID_A", "icon": 8}]},
        }
        data = FakeGameData([_item("IID_A")])

        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = Path(temp_dir) / "items.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            with mock.patch.object(change_packages, "_item_definition", return_value=ITEM_DEF):
                with self.assertRaisesRegex(ValueError, "item change package"):
                    change_packages.import_items(project, data, str(package_path))


if __name__ == "__main__":
    unittest.main()
