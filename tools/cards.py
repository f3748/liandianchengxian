#!/usr/bin/env python3
"""Validate cards.json and deterministically generate cards-data.js."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "cards.json"
GENERATED_PATH = ROOT / "cards-data.js"

TOP_LEVEL_KEYS = {
    "schemaVersion",
    "cards",
    "extraHistoryCards",
    "proverbCards",
}
GROUPS = ("cards", "extraHistoryCards", "proverbCards")
CARD_KEYS = {
    "title",
    "level",
    "type",
    "tags",
    "mainTag",
    "subTag",
    "timeText",
    "place",
    "summary",
    "fields",
    "relationItems",
    "relations",
    "source",
    "id",
}
LEVELS = {"S", "A", "B", "C"}
CARD_TYPES = {
    "事件卡",
    "人物卡",
    "作品卡",
    "俗语卡",
    "制度/文本卡",
    "概念/思潮卡",
    "组织/机构卡",
}
TAGS = {"政治与制度", "经济与社会", "战争与外交", "文化与思想"}
GROUP_SOURCES = {
    "cards": "history",
    "extraHistoryCards": "history",
    "proverbCards": "proverb",
}
GROUP_ID_PATTERNS = {
    "cards": re.compile(r"card[1-9]\d*\Z"),
    "extraHistoryCards": re.compile(r"extra[1-9]\d*\Z"),
    "proverbCards": re.compile(r"proverb[1-9]\d*\Z"),
}

# These two historical cards already shipped with proverb-prefixed IDs. Renaming
# them would break relations and permalinks, so v1 preserves only these exact
# exceptions and rejects any new prefix mismatch.
LEGACY_ID_EXCEPTIONS = {
    ("extraHistoryCards", "proverb31"): "德国军队",
    ("extraHistoryCards", "proverb32"): "现代战争的标准化",
}

RELATION_REVERSES = {
    "← 前因": "→ 后果",
    "→ 后果": "← 前因",
    "↔ 相关": "↔ 相关",
    "✗ 对立/冲突": "✗ 对立/冲突",
    "↔ 同时期参考": "↔ 同时期参考",
}

REQUIRED_MIRRORS = {
    "标题": "title",
    "分级": "level",
    "类型": "type",
    "主标签": "mainTag",
    "时间": "timeText",
    "一句话概括": "summary",
}


class DuplicateKeyError(ValueError):
    pass


class InvalidConstantError(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def reject_invalid_constant(value: str) -> None:
    raise InvalidConstantError(f"invalid JSON numeric constant {value!r}")


class ValidationReport:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str, str]] = []
        self.card_count = 0
        self.relation_count = 0

    def error(self, path: str, message: str, card_id: str = "-") -> None:
        self.errors.append((card_id, path, message))

    def print_errors(self, limit: int = 200) -> None:
        ordered = sorted(self.errors)
        for card_id, path, message in ordered[:limit]:
            print(f"ERROR [{card_id}] {path}: {message}", file=sys.stderr)
        if len(ordered) > limit:
            print(
                f"ERROR: showing {limit} of {len(ordered)} validation errors",
                file=sys.stderr,
            )

    def print_success(self, action: str) -> None:
        print(
            f"Cards {action} passed: {self.card_count} cards, "
            f"{self.relation_count} directed relations."
        )


def load_source(report: ValidationReport) -> Any | None:
    try:
        raw_bytes = SOURCE_PATH.read_bytes()
    except OSError as exc:
        report.error("$", f"cannot read {SOURCE_PATH.name}: {exc}")
        return None

    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        report.error("$", "UTF-8 BOM is not allowed")
        return None

    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        report.error("$", f"file is not valid UTF-8: {exc}")
        return None

    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_invalid_constant,
        )
    except (json.JSONDecodeError, DuplicateKeyError, InvalidConstantError) as exc:
        report.error("$", f"invalid JSON: {exc}")
        return None


def describe_keys(actual: set[str], expected: set[str]) -> str:
    parts = []
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        parts.append(f"missing keys {missing}")
    if extra:
        parts.append(f"unknown keys {extra}")
    return "; ".join(parts)


def validate_exact_keys(
    value: Any,
    expected: set[str],
    path: str,
    report: ValidationReport,
    card_id: str = "-",
) -> bool:
    if not isinstance(value, dict):
        report.error(path, f"expected object, got {type(value).__name__}", card_id)
        return False
    actual = set(value)
    if actual != expected:
        report.error(path, describe_keys(actual, expected), card_id)
        return False
    return True


def require_string(
    card: dict[str, Any],
    key: str,
    path: str,
    report: ValidationReport,
    card_id: str,
    *,
    allow_empty: bool = False,
) -> str | None:
    value = card.get(key)
    if not isinstance(value, str):
        report.error(
            f"{path}.{key}",
            f"expected string, got {type(value).__name__}",
            card_id,
        )
        return None
    if not allow_empty and not value:
        report.error(f"{path}.{key}", "must not be empty", card_id)
    return value


def validate_fields(
    card: dict[str, Any], path: str, report: ValidationReport, card_id: str
) -> None:
    fields = card.get("fields")
    fields_path = f"{path}.fields"
    if not isinstance(fields, list):
        report.error(
            fields_path,
            f"expected array, got {type(fields).__name__}",
            card_id,
        )
        return
    if not fields:
        report.error(fields_path, "must not be empty", card_id)
        return

    by_label: dict[str, str] = {}
    for index, field in enumerate(fields):
        field_path = f"{fields_path}[{index}]"
        if not validate_exact_keys(
            field, {"label", "value"}, field_path, report, card_id
        ):
            continue
        label = field["label"]
        value = field["value"]
        if not isinstance(label, str):
            report.error(
                f"{field_path}.label",
                f"expected string, got {type(label).__name__}",
                card_id,
            )
            continue
        if not label:
            report.error(f"{field_path}.label", "must not be empty", card_id)
            continue
        if not isinstance(value, str):
            report.error(
                f"{field_path}.value",
                f"expected string, got {type(value).__name__}",
                card_id,
            )
            continue
        if not value and not (label == "副标签" and card.get("subTag") == ""):
            report.error(f"{field_path}.value", "must not be empty", card_id)
        if label in by_label:
            report.error(f"{field_path}.label", f"duplicate field label {label!r}", card_id)
        else:
            by_label[label] = value

    for label, key in REQUIRED_MIRRORS.items():
        if label not in by_label:
            report.error(fields_path, f"missing mirrored field {label!r}", card_id)
        elif by_label[label] != card.get(key):
            report.error(
                fields_path,
                f"field {label!r} does not match top-level {key!r}",
                card_id,
            )

    sub_tag = card.get("subTag")
    if sub_tag:
        if "副标签" not in by_label:
            report.error(fields_path, "missing mirrored field '副标签'", card_id)
        elif by_label["副标签"] != sub_tag:
            report.error(
                fields_path,
                "field '副标签' does not match top-level 'subTag'",
                card_id,
            )
    elif "副标签" in by_label and by_label["副标签"] != "":
        report.error(
            fields_path,
            "field '副标签' must be empty when top-level 'subTag' is empty",
            card_id,
        )

    place_label = "地区" if card.get("source") == "proverb" else "地点"
    if place_label not in by_label:
        report.error(fields_path, f"missing mirrored field {place_label!r}", card_id)
    elif by_label[place_label] != card.get("place"):
        report.error(
            fields_path,
            f"field {place_label!r} does not match top-level 'place'",
            card_id,
        )

    if not by_label.get("出处"):
        report.error(fields_path, "missing non-empty field '出处'", card_id)


def validate_tags(
    card: dict[str, Any], path: str, report: ValidationReport, card_id: str
) -> None:
    tags = card.get("tags")
    if not isinstance(tags, list):
        report.error(
            f"{path}.tags",
            f"expected array, got {type(tags).__name__}",
            card_id,
        )
        return
    if any(not isinstance(tag, str) for tag in tags):
        report.error(f"{path}.tags", "all tags must be strings", card_id)
        return
    invalid = sorted(set(tags) - TAGS)
    if invalid:
        report.error(f"{path}.tags", f"unknown tags {invalid}", card_id)
    if len(tags) != len(set(tags)):
        report.error(f"{path}.tags", "tags must not contain duplicates", card_id)
    main_tag = card.get("mainTag")
    sub_tag = card.get("subTag")
    expected = [main_tag] if sub_tag == "" else [main_tag, sub_tag]
    if tags != expected:
        report.error(
            f"{path}.tags",
            f"expected {expected!r} from mainTag/subTag",
            card_id,
        )
    if sub_tag and main_tag == sub_tag:
        report.error(f"{path}.subTag", "must differ from mainTag", card_id)


def validate_relation_arrays(
    card: dict[str, Any], path: str, report: ValidationReport, card_id: str
) -> None:
    relation_items = card.get("relationItems")
    relations = card.get("relations")
    if not isinstance(relation_items, list):
        report.error(
            f"{path}.relationItems",
            f"expected array, got {type(relation_items).__name__}",
            card_id,
        )
    elif any(not isinstance(item, str) for item in relation_items):
        report.error(
            f"{path}.relationItems", "all relationItems must be strings", card_id
        )

    if not isinstance(relations, list):
        report.error(
            f"{path}.relations",
            f"expected array, got {type(relations).__name__}",
            card_id,
        )
        return

    texts: list[Any] = []
    for index, relation in enumerate(relations):
        relation_path = f"{path}.relations[{index}]"
        if not validate_exact_keys(
            relation, {"text", "id"}, relation_path, report, card_id
        ):
            continue
        text = relation["text"]
        target_id = relation["id"]
        if not isinstance(text, str) or not text:
            report.error(f"{relation_path}.text", "must be a non-empty string", card_id)
        if not isinstance(target_id, str) or not target_id:
            report.error(f"{relation_path}.id", "must be a non-empty string", card_id)
        texts.append(text)

    if isinstance(relation_items, list) and relation_items != texts:
        report.error(
            f"{path}.relationItems",
            "must exactly equal relations[].text in the same order",
            card_id,
        )


def validate_card(
    card: Any,
    group: str,
    index: int,
    report: ValidationReport,
) -> tuple[str | None, str | None]:
    path = f"$.{group}[{index}]"
    preliminary_id = card.get("id") if isinstance(card, dict) else None
    card_id = preliminary_id if isinstance(preliminary_id, str) else "-"
    if not validate_exact_keys(card, CARD_KEYS, path, report, card_id):
        return None, None

    string_keys = (
        "title",
        "level",
        "type",
        "mainTag",
        "timeText",
        "place",
        "summary",
        "source",
        "id",
    )
    values = {
        key: require_string(card, key, path, report, card_id) for key in string_keys
    }
    values["subTag"] = require_string(
        card, "subTag", path, report, card_id, allow_empty=True
    )

    title = values["title"]
    valid_id = values["id"]
    if valid_id:
        expected_pattern = GROUP_ID_PATTERNS[group]
        if not expected_pattern.fullmatch(valid_id):
            legacy_title = LEGACY_ID_EXCEPTIONS.get((group, valid_id))
            if legacy_title is None:
                report.error(
                    f"{path}.id",
                    f"does not match the ID prefix for {group}",
                    card_id,
                )
            elif title != legacy_title:
                report.error(
                    f"{path}.id",
                    f"legacy exception is reserved for title {legacy_title!r}",
                    card_id,
                )

    if values["level"] and values["level"] not in LEVELS:
        report.error(f"{path}.level", f"unknown level {values['level']!r}", card_id)
    if values["type"] and values["type"] not in CARD_TYPES:
        report.error(f"{path}.type", f"unknown card type {values['type']!r}", card_id)
    elif group == "proverbCards" and values["type"] != "俗语卡":
        report.error(f"{path}.type", "proverbCards must contain only '俗语卡'", card_id)
    elif group != "proverbCards" and values["type"] == "俗语卡":
        report.error(f"{path}.type", f"'俗语卡' must be stored in proverbCards", card_id)
    if values["mainTag"] and values["mainTag"] not in TAGS:
        report.error(
            f"{path}.mainTag", f"unknown mainTag {values['mainTag']!r}", card_id
        )
    if values["subTag"] and values["subTag"] not in TAGS:
        report.error(
            f"{path}.subTag", f"unknown subTag {values['subTag']!r}", card_id
        )

    expected_source = GROUP_SOURCES[group]
    if values["source"] != expected_source:
        report.error(
            f"{path}.source",
            f"expected {expected_source!r} for {group}",
            card_id,
        )

    validate_tags(card, path, report, card_id)
    validate_fields(card, path, report, card_id)
    validate_relation_arrays(card, path, report, card_id)
    return valid_id, title


def parse_relation_text(text: str) -> tuple[str, str] | None:
    for kind in RELATION_REVERSES:
        prefix = f"{kind}："
        if text.startswith(prefix):
            target_title = text[len(prefix) :]
            if target_title:
                return kind, target_title
            return None
    return None


def validate_relations(
    cards: list[tuple[str, int, dict[str, Any]]],
    by_id: dict[str, dict[str, Any]],
    report: ValidationReport,
) -> None:
    edges: dict[tuple[str, str], tuple[str, str, str]] = {}

    for group, index, card in cards:
        source_id = card.get("id")
        if not isinstance(source_id, str):
            continue
        relations = card.get("relations")
        if not isinstance(relations, list):
            continue
        seen_targets: set[str] = set()
        for relation_index, relation in enumerate(relations):
            path = f"$.{group}[{index}].relations[{relation_index}]"
            if not isinstance(relation, dict):
                continue
            target_id = relation.get("id")
            text = relation.get("text")
            if not isinstance(target_id, str) or not isinstance(text, str):
                continue
            report.relation_count += 1
            if target_id in seen_targets:
                report.error(path, f"duplicate relation target {target_id!r}", source_id)
            seen_targets.add(target_id)
            if target_id == source_id:
                report.error(path, "self relation is not allowed", source_id)
            target = by_id.get(target_id)
            if target is None:
                report.error(path, f"unknown target ID {target_id!r}", source_id)

            parsed = parse_relation_text(text)
            if parsed is None:
                report.error(path, "invalid relation text or relation kind", source_id)
                continue
            kind, target_title = parsed
            if target is not None and target_title != target.get("title"):
                report.error(
                    path,
                    f"target title {target_title!r} does not match {target.get('title')!r}",
                    source_id,
                )
            edge_key = (source_id, target_id)
            if edge_key in edges:
                report.error(path, f"duplicate edge to {target_id!r}", source_id)
            else:
                edges[edge_key] = (kind, path, source_id)

    for (source_id, target_id), (kind, path, card_id) in sorted(edges.items()):
        reverse = edges.get((target_id, source_id))
        if reverse is None:
            report.error(path, f"missing reverse relation from {target_id!r}", card_id)
            continue
        expected_kind = RELATION_REVERSES[kind]
        if reverse[0] != expected_kind:
            report.error(
                path,
                f"reverse relation kind is {reverse[0]!r}, expected {expected_kind!r}",
                card_id,
            )


def validate(data: Any, report: ValidationReport) -> None:
    if not validate_exact_keys(data, TOP_LEVEL_KEYS, "$", report):
        return

    schema_version = data.get("schemaVersion")
    if type(schema_version) is not int or schema_version != 1:
        report.error(
            "$.schemaVersion",
            f"expected integer 1, got {schema_version!r}",
        )

    cards: list[tuple[str, int, dict[str, Any]]] = []
    by_id: dict[str, dict[str, Any]] = {}
    title_owners: dict[str, str] = {}

    for group in GROUPS:
        group_cards = data.get(group)
        if not isinstance(group_cards, list):
            report.error(
                f"$.{group}",
                f"expected array, got {type(group_cards).__name__}",
            )
            continue
        for index, card in enumerate(group_cards):
            valid_id, title = validate_card(card, group, index, report)
            if not isinstance(card, dict):
                continue
            cards.append((group, index, card))
            report.card_count += 1
            if valid_id:
                if valid_id in by_id:
                    report.error(
                        f"$.{group}[{index}].id",
                        f"duplicate ID already used by {by_id[valid_id].get('title')!r}",
                        valid_id,
                    )
                else:
                    by_id[valid_id] = card
            if title:
                owner = title_owners.get(title)
                if owner is not None:
                    report.error(
                        f"$.{group}[{index}].title",
                        f"duplicate title already used by {owner!r}",
                        valid_id or "-",
                    )
                else:
                    title_owners[title] = valid_id or f"{group}[{index}]"

    validate_relations(cards, by_id, report)


def generated_bytes(data: Any) -> bytes:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return f"window.CARD_DATA={payload};\n".encode("utf-8")


def load_and_validate() -> tuple[Any | None, ValidationReport]:
    report = ValidationReport()
    data = load_source(report)
    if data is not None:
        validate(data, report)
    return data, report


def run_check() -> int:
    _, report = load_and_validate()
    if report.errors:
        report.print_errors()
        return 1
    report.print_success("check")
    return 0


def run_verify() -> int:
    data, report = load_and_validate()
    if report.errors or data is None:
        report.print_errors()
        return 1

    expected = generated_bytes(data)
    try:
        actual = GENERATED_PATH.read_bytes()
    except OSError as exc:
        report.error("$generated", f"cannot read {GENERATED_PATH.name}: {exc}")
        report.print_errors()
        return 1

    if actual != expected:
        expected_hash = hashlib.sha256(expected).hexdigest()
        actual_hash = hashlib.sha256(actual).hexdigest()
        report.error(
            "$generated",
            f"{GENERATED_PATH.name} is stale or modified "
            f"(expected sha256 {expected_hash}, got {actual_hash}); run build",
        )
        report.print_errors()
        return 1

    report.print_success("verify")
    return 0


def atomic_write(path: Path, content: bytes) -> None:
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def run_build() -> int:
    data, report = load_and_validate()
    if report.errors or data is None:
        report.print_errors()
        return 1

    expected = generated_bytes(data)
    try:
        actual = GENERATED_PATH.read_bytes()
    except FileNotFoundError:
        actual = None
    except OSError as exc:
        report.error("$generated", f"cannot read {GENERATED_PATH.name}: {exc}")
        report.print_errors()
        return 1

    if actual == expected:
        report.print_success("build")
        print(f"{GENERATED_PATH.name} is already up to date; no file written.")
        return 0

    try:
        atomic_write(GENERATED_PATH, expected)
    except OSError as exc:
        report.error("$generated", f"cannot write {GENERATED_PATH.name}: {exc}")
        report.print_errors()
        return 1

    report.print_success("build")
    print(f"Generated {GENERATED_PATH.name} from {SOURCE_PATH.name}.")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate cards.json and manage the generated cards-data.js file."
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="verify",
        choices=("check", "build", "verify"),
        help="check source, build generated data, or verify both (default: verify)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "check":
        return run_check()
    if args.command == "build":
        return run_build()
    return run_verify()


if __name__ == "__main__":
    raise SystemExit(main())
