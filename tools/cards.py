#!/usr/bin/env python3
"""Validate cards.json and deterministically generate cards-data.js."""

from __future__ import annotations

import argparse
import calendar
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
REQUIRED_CARD_KEYS = {
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
OPTIONAL_CARD_KEYS = {"timelineInclude", "timeline"}
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

TIMELINE_KINDS = {"point", "range", "compound"}
TIMELINE_ERAS = {"BCE", "CE"}
TIMELINE_PRECISIONS = {"day", "month", "year", "decade", "century", "era"}
TIMELINE_QUALIFIERS = {"exact", "circa", "before", "after"}

# Phase-one migration manifest. Keeping this list in the validator makes a
# partial, accidental, or expanded migration fail loudly in CI/review.
BCE_PHASE_ONE_EXPECTED = {
    "extra1925": ("point", 1754, None, "circa"), "extra1928": ("range", 1200, 1150, "circa"),
    "extra1931": ("range", 499, 449, "exact"), "extra1932": ("range", 334, 323, "exact"),
    "extra1934": ("range", 264, 27, "circa"), "extra1942": ("range", 268, 232, "circa"),
    "extra1957": ("range", 264, 146, "exact"), "extra1960": ("range", 49, 27, "exact"),
    "extra1995": ("range", 112, 111, "exact"), "extra2036": ("range", 58, 50, "exact"),
    "extra2039": ("range", 431, 404, "exact"), "extra2040": ("range", 323, 281, "exact"),
    "extra2041": ("range", 200, 30, "circa"), "extra2050": ("range", 1300, 700, "circa"),
    "extra2070": ("range", 89, 63, "exact"), "extra2073": ("range", 214, 168, "exact"),
    "extra2087": ("range", 327, 325, "exact"), "extra2138": ("range", 237, 218, "circa"),
    "extra2139": ("range", 153, 133, "exact"), "extra2193": ("point", 621, None, "circa"),
    "extra2200": ("point", 490, None, "exact"), "extra2201": ("point", 480, None, "exact"),
    "extra2202": ("point", 480, None, "exact"), "extra2206": ("range", 430, 426, "exact"),
    "extra2207": ("point", 416, None, "exact"), "extra2208": ("range", 415, 413, "exact"),
    "extra2209": ("range", 404, 403, "exact"), "extra2212": ("range", 371, 362, "exact"),
    "extra2213": ("range", 359, 336, "circa"), "extra2219": ("point", 287, None, "exact"),
    "extra2226": ("range", 280, 275, "exact"), "extra2229": ("range", 264, 241, "exact"),
    "extra2230": ("range", 218, 201, "exact"), "extra2231": ("point", 216, None, "exact"),
    "extra2233": ("point", 202, None, "exact"), "extra2235": ("range", 133, 121, "exact"),
    "extra2236": ("range", 91, 87, "exact"), "extra2238": ("range", 88, 79, "exact"),
    "extra2240": ("point", 49, None, "exact"), "extra2241": ("range", 43, 30, "exact"),
    "extra2306": ("point", 399, None, "exact"), "extra2310": ("point", 335, None, "circa"),
    "extra2349": ("point", 186, None, "exact"), "extra2350": ("range", 167, 63, "exact"),
    "extra2411": ("point", 539, None, "exact"), "extra2474": ("range", 1400, 1200, "circa"),
}
BCE_PHASE_ONE_IDS = set(BCE_PHASE_ONE_EXPECTED)

# Editorially approved complex-date batch. Endpoint tuples are
# (era, year, datePrecision, qualifier) and are locked exactly so later edits
# cannot silently flatten century/decade precision or asymmetric qualifiers.
PHASE_TWO_EXPECTED = {
    "extra1937": ("range", ("BCE", 230, "year", "exact"), ("BCE", 221, "year", "exact")),
    "extra1958": ("range", ("BCE", 359, "year", "circa"), ("BCE", 338, "year", "exact")),
    "extra393": ("range", ("CE", 301, "century", "circa"), ("CE", 600, "century", "circa")),
    "extra403": ("range", ("CE", 1001, "century", "circa"), ("CE", 1400, "century", "circa")),
    "extra952": ("range", ("CE", 1850, "decade", "circa"), ("CE", 1910, "decade", "circa")),
    "extra2118": ("range", ("CE", 1, "century", "circa"), ("CE", 300, "century", "circa")),
    "extra2190": ("range", ("BCE", 800, "century", "circa"), ("BCE", 601, "century", "circa")),
    "extra2710": ("point", ("CE", 480, "decade", "circa"), None),
    "extra1031": ("range", ("CE", 1250, "decade", "circa"), ("CE", 1300, "decade", "circa")),
    "extra1043": ("range", ("CE", 1201, "century", "circa"), ("CE", 1500, "century", "circa")),
    "extra1911": ("range", ("CE", 801, "century", "circa"), ("CE", 1300, "century", "circa")),
    "extra1090": ("range", ("CE", 1450, "decade", "after"), ("CE", 1900, "century", "circa")),
    "extra1100": ("range", ("CE", 1580, "decade", "circa"), ("CE", 1800, "century", "circa")),
    "extra1110": ("range", ("CE", 1530, "decade", "circa"), ("CE", 1580, "decade", "circa")),
}
PHASE_TWO_IDS = set(PHASE_TWO_EXPECTED)
STRUCTURED_TIMELINE_IDS = BCE_PHASE_ONE_IDS | PHASE_TWO_IDS

# First controlled compound-timeline batch. Compound parts deliberately support
# only closed, single-era, year-precision markers and segments in this phase.
COMPOUND_PHASE_ONE_EXPECTED = {
    "extra1971": (
        "first-journey",
        (
            ("first-journey", "第一次出使", "segment", ("BCE", 138, "year", "circa"), ("BCE", 126, "year", "circa")),
            ("second-journey", "第二次出使", "marker", ("BCE", 119, "year", "circa"), None),
        ),
    ),
    "extra2114": (
        "monopoly-established",
        (
            ("monopoly-established", "专卖建立", "marker", ("BCE", 119, "year", "circa"), None),
            ("salt-iron-debate", "盐铁会议", "marker", ("BCE", 81, "year", "exact"), None),
        ),
    ),
    "extra2225": (
        "first-war",
        (
            ("first-war", "第一次战争", "segment", ("BCE", 343, "year", "circa"), ("BCE", 341, "year", "circa")),
            ("second-war", "第二次战争", "segment", ("BCE", 326, "year", "circa"), ("BCE", 304, "year", "circa")),
            ("third-war", "第三次战争", "segment", ("BCE", 298, "year", "circa"), ("BCE", 290, "year", "circa")),
        ),
    ),
    "extra2242": (
        "first-settlement",
        (
            ("first-settlement", "第一次宪制安排", "marker", ("BCE", 27, "year", "exact"), None),
            ("second-settlement", "第二次宪制安排", "marker", ("BCE", 23, "year", "exact"), None),
        ),
    ),
    "extra640": (
        "project-phase",
        (
            ("project-phase", "项目推进", "segment", ("CE", 1899, "year", "circa"), ("CE", 1918, "year", "exact")),
            ("construction-start", "施工启动", "marker", ("CE", 1903, "year", "exact"), None),
        ),
    ),
}
COMPOUND_PHASE_ONE_IDS = set(COMPOUND_PHASE_ONE_EXPECTED)
STRUCTURED_TIMELINE_IDS |= COMPOUND_PHASE_ONE_IDS

# Representative unmigrated CE cards protect the legacy inference contract.
# These exact snapshots are intentionally independent of structured timeline
# data so existing CE positions cannot drift unnoticed.
LEGACY_CE_GOLDEN = {
    "card7": ("1918年至1919年", "range", "1918-06-30", "1919-12-31"),
    "card59": ("1919年6月28日", "point", "1919-06-28", None),
    "extra662": ("1918年3月3日", "point", "1918-03-03", None),
    "extra667": ("1918年11月11日", "point", "1918-11-11", None),
    "extra1232": ("1961年4—12月，1962年执行判决", "range", "1961-04-15", "1961-12-31"),
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


def timeline_endpoint_value(endpoint: dict[str, Any]) -> tuple[int, int, int]:
    """Return a sortable proleptic-Gregorian key using astronomical years."""
    year = endpoint["year"] if endpoint["era"] == "CE" else 1 - endpoint["year"]
    return year, endpoint.get("month", 6), endpoint.get("day", 15)


def validate_timeline_endpoint(
    endpoint: Any,
    path: str,
    report: ValidationReport,
    card_id: str,
) -> bool:
    required = {"era", "year", "datePrecision", "qualifier"}
    allowed = required | {"month", "day"}
    if not isinstance(endpoint, dict):
        report.error(path, f"expected object, got {type(endpoint).__name__}", card_id)
        return False
    actual = set(endpoint)
    if not required.issubset(actual) or not actual.issubset(allowed):
        report.error(path, describe_keys(actual, required), card_id)
        unknown = sorted(actual - allowed)
        if unknown:
            report.error(path, f"unknown keys {unknown}", card_id)
        return False

    valid = True
    era = endpoint.get("era")
    if era not in TIMELINE_ERAS:
        report.error(f"{path}.era", f"expected one of {sorted(TIMELINE_ERAS)}", card_id)
        valid = False
    year = endpoint.get("year")
    if type(year) is not int or year <= 0:
        report.error(f"{path}.year", "must be a positive integer; source year 0 is forbidden", card_id)
        valid = False
    precision = endpoint.get("datePrecision")
    if precision not in TIMELINE_PRECISIONS:
        report.error(f"{path}.datePrecision", f"expected one of {sorted(TIMELINE_PRECISIONS)}", card_id)
        valid = False
    qualifier = endpoint.get("qualifier")
    if qualifier not in TIMELINE_QUALIFIERS:
        report.error(f"{path}.qualifier", f"expected one of {sorted(TIMELINE_QUALIFIERS)}", card_id)
        valid = False

    month = endpoint.get("month")
    day = endpoint.get("day")
    if month is not None and (type(month) is not int or not 1 <= month <= 12):
        report.error(f"{path}.month", "must be an integer from 1 to 12", card_id)
        valid = False
    if day is not None and (type(day) is not int or not 1 <= day <= 31):
        report.error(f"{path}.day", "must be an integer from 1 to 31", card_id)
        valid = False
    if (
        valid
        and month is not None
        and day is not None
        and day > calendar.monthrange(year if era == "CE" else 1 - year, month)[1]
    ):
        report.error(f"{path}.day", "is not valid for the given month/year", card_id)
        valid = False
    if day is not None and month is None:
        report.error(f"{path}.day", "requires month", card_id)
        valid = False
    if precision == "day" and (month is None or day is None):
        report.error(path, "day precision requires month and day", card_id)
        valid = False
    if precision == "month" and month is None:
        report.error(path, "month precision requires month", card_id)
        valid = False
    if precision in {"year", "decade", "century", "era"} and (month is not None or day is not None):
        report.error(path, f"{precision} precision must not include month/day", card_id)
        valid = False
    return valid


def validate_timeline(
    card: dict[str, Any], path: str, report: ValidationReport, card_id: str
) -> None:
    include = card.get("timelineInclude")
    timeline = card.get("timeline")
    if "timelineInclude" in card and type(include) is not bool:
        report.error(f"{path}.timelineInclude", "must be boolean", card_id)
        return
    if include is False:
        if "timeline" in card:
            report.error(f"{path}.timeline", "must be absent when timelineInclude is false", card_id)
        return
    if include is True and "timeline" not in card:
        report.error(f"{path}.timeline", "is required when timelineInclude is true", card_id)
        return
    if "timeline" in card and include is not True:
        report.error(f"{path}.timelineInclude", "must be true when timeline is present", card_id)
        return
    if timeline is None:
        return
    if not isinstance(timeline, dict):
        report.error(f"{path}.timeline", f"expected object, got {type(timeline).__name__}", card_id)
        return

    kind = timeline.get("kind")
    if kind == "compound":
        if not validate_exact_keys(timeline, {"kind", "defaultPart", "parts"}, f"{path}.timeline", report, card_id):
            return
        default_part = timeline.get("defaultPart")
        parts = timeline.get("parts")
        if not isinstance(default_part, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", default_part):
            report.error(f"{path}.timeline.defaultPart", "must be a stable lowercase kebab-case key", card_id)
        if not isinstance(parts, list) or len(parts) < 2:
            report.error(f"{path}.timeline.parts", "must contain at least two parts", card_id)
            return
        keys: set[str] = set()
        era: str | None = None
        previous_start: tuple[int, int, int] | None = None
        previous_segment_end: tuple[int, int, int] | None = None
        for index, part in enumerate(parts):
            part_path = f"{path}.timeline.parts[{index}]"
            role = part.get("role") if isinstance(part, dict) else None
            expected_part_keys = {"key", "label", "role", "start"} | ({"end"} if role == "segment" else set())
            if not validate_exact_keys(part, expected_part_keys, part_path, report, card_id):
                continue
            key = part.get("key")
            label = part.get("label")
            if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", key):
                report.error(f"{part_path}.key", "must be a stable lowercase kebab-case key", card_id)
            elif key in keys:
                report.error(f"{part_path}.key", f"duplicate compound part key {key!r}", card_id)
            else:
                keys.add(key)
            if not isinstance(label, str) or not label.strip() or len(label) > 16:
                report.error(f"{part_path}.label", "must be a non-empty short label of at most 16 characters", card_id)
            if role not in {"marker", "segment"}:
                report.error(f"{part_path}.role", "expected 'marker' or 'segment'", card_id)
                continue
            start_valid = validate_timeline_endpoint(part.get("start"), f"{part_path}.start", report, card_id)
            end_valid = role == "marker" or validate_timeline_endpoint(part.get("end"), f"{part_path}.end", report, card_id)
            endpoints = [part.get("start")] + ([part.get("end")] if role == "segment" else [])
            if start_valid and end_valid:
                if any(endpoint["datePrecision"] != "year" for endpoint in endpoints):
                    report.error(part_path, "phase-one compound endpoints must use year precision", card_id)
                if any(endpoint["qualifier"] not in {"exact", "circa"} for endpoint in endpoints):
                    report.error(part_path, "phase-one compound qualifiers must be exact or circa", card_id)
                part_era = endpoints[0]["era"]
                if any(endpoint["era"] != part_era for endpoint in endpoints):
                    report.error(part_path, "compound segments must be single-era", card_id)
                if era is None:
                    era = part_era
                elif era != part_era:
                    report.error(f"{path}.timeline.parts", "all compound parts must use one era", card_id)
                start_value = timeline_endpoint_value(endpoints[0])
                if role == "segment":
                    end_value = timeline_endpoint_value(endpoints[1])
                    if start_value > end_value:
                        report.error(part_path, "segment start must not be later than end", card_id)
                    if previous_segment_end is not None and start_value <= previous_segment_end:
                        report.error(f"{path}.timeline.parts", "continuous segments must not overlap", card_id)
                    previous_segment_end = end_value
                if previous_start is not None and start_value < previous_start:
                    report.error(f"{path}.timeline.parts", "parts must be ordered chronologically by start", card_id)
                previous_start = start_value
        if isinstance(default_part, str) and default_part not in keys:
            report.error(f"{path}.timeline.defaultPart", "must reference an existing part key", card_id)
        return

    expected = {"kind", "start"} if kind == "point" else {"kind", "start", "end"}
    if not validate_exact_keys(timeline, expected, f"{path}.timeline", report, card_id):
        return
    if kind not in TIMELINE_KINDS:
        report.error(f"{path}.timeline.kind", f"expected one of {sorted(TIMELINE_KINDS)}", card_id)
        return
    start_valid = validate_timeline_endpoint(timeline.get("start"), f"{path}.timeline.start", report, card_id)
    end_valid = True
    if kind == "range":
        end_valid = validate_timeline_endpoint(timeline.get("end"), f"{path}.timeline.end", report, card_id)
    if start_valid and end_valid and kind == "range":
        if timeline["start"]["era"] != timeline["end"]["era"]:
            report.error(f"{path}.timeline", "cross-era ranges are not supported by separated era views", card_id)
            return
        if timeline_endpoint_value(timeline["start"]) > timeline_endpoint_value(timeline["end"]):
            report.error(f"{path}.timeline", "start must not be later than end", card_id)


def validate_card(
    card: Any,
    group: str,
    index: int,
    report: ValidationReport,
) -> tuple[str | None, str | None]:
    path = f"$.{group}[{index}]"
    preliminary_id = card.get("id") if isinstance(card, dict) else None
    card_id = preliminary_id if isinstance(preliminary_id, str) else "-"
    if not isinstance(card, dict):
        report.error(path, f"expected object, got {type(card).__name__}", card_id)
        return None, None
    actual_keys = set(card)
    if not REQUIRED_CARD_KEYS.issubset(actual_keys) or not actual_keys.issubset(REQUIRED_CARD_KEYS | OPTIONAL_CARD_KEYS):
        report.error(path, describe_keys(actual_keys, REQUIRED_CARD_KEYS), card_id)
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
    validate_timeline(card, path, report, card_id)
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


def validate_timeline_migration(
    by_id: dict[str, dict[str, Any]], report: ValidationReport
) -> None:
    structured_ids = {
        card_id for card_id, card in by_id.items()
        if card.get("timelineInclude") is True or "timeline" in card
    }
    missing = sorted(STRUCTURED_TIMELINE_IDS - structured_ids)
    extra = sorted(structured_ids - STRUCTURED_TIMELINE_IDS)
    if missing:
        report.error("$timelineMigration", f"missing approved structured timeline IDs {missing}")
    if extra:
        report.error("$timelineMigration", f"unexpected structured timeline IDs {extra}")
    if len(structured_ids) != 65:
        report.error("$timelineMigration", f"expected exactly 65 structured cards, got {len(structured_ids)}")
    if timeline_endpoint_value({"era": "BCE", "year": 1})[0] != 0 or timeline_endpoint_value({"era": "BCE", "year": 2})[0] != -1:
        report.error("$timelineMigration", "astronomical conversion must map 1 BCE to 0 and 2 BCE to -1")
    for card_id in sorted(BCE_PHASE_ONE_IDS & structured_ids):
        timeline = by_id[card_id].get("timeline")
        if not isinstance(timeline, dict):
            continue
        endpoints = [timeline.get("start")]
        if timeline.get("kind") == "range":
            endpoints.append(timeline.get("end"))
        if any(not isinstance(endpoint, dict) or endpoint.get("era") != "BCE" for endpoint in endpoints):
            report.error("$timelineMigration", "phase-one endpoints must all use BCE", card_id)
            continue
        expected_kind, expected_start, expected_end, expected_qualifier = BCE_PHASE_ONE_EXPECTED[card_id]
        actual = (
            timeline.get("kind"),
            timeline.get("start", {}).get("year"),
            timeline.get("end", {}).get("year") if timeline.get("kind") == "range" else None,
            timeline.get("start", {}).get("qualifier"),
        )
        if actual != (expected_kind, expected_start, expected_end, expected_qualifier):
            report.error("$timelineMigration", f"expected phase-one value {(expected_kind, expected_start, expected_end, expected_qualifier)!r}, got {actual!r}", card_id)
        if any(endpoint.get("datePrecision") != "year" for endpoint in endpoints):
            report.error("$timelineMigration", "phase-one precision must be year", card_id)
        if any(endpoint.get("qualifier") != expected_qualifier for endpoint in endpoints):
            report.error("$timelineMigration", f"phase-one qualifier must be {expected_qualifier!r}", card_id)

    valid_phase_cards = [
        (card_id, by_id[card_id]["timeline"]["start"])
        for card_id in BCE_PHASE_ONE_IDS
        if isinstance(by_id.get(card_id, {}).get("timeline", {}).get("start"), dict)
    ]
    expected_order = [card_id for card_id, _ in sorted(valid_phase_cards, key=lambda item: (-item[1]["year"], item[0]))]
    astronomical_order = [card_id for card_id, _ in sorted(valid_phase_cards, key=lambda item: (timeline_endpoint_value(item[1]), item[0]))]
    if astronomical_order != expected_order:
        report.error("$timelineMigration", "BCE chronological order does not match descending source-year order")

    for card_id in sorted(PHASE_TWO_IDS & structured_ids):
        timeline = by_id[card_id].get("timeline")
        if not isinstance(timeline, dict):
            continue
        expected_kind, expected_start, expected_end = PHASE_TWO_EXPECTED[card_id]
        actual_start = timeline.get("start")
        actual_end = timeline.get("end") if timeline.get("kind") == "range" else None
        endpoint_tuple = lambda endpoint: (
            endpoint.get("era"),
            endpoint.get("year"),
            endpoint.get("datePrecision"),
            endpoint.get("qualifier"),
        ) if isinstance(endpoint, dict) else None
        actual = (timeline.get("kind"), endpoint_tuple(actual_start), endpoint_tuple(actual_end))
        expected = (expected_kind, expected_start, expected_end)
        if actual != expected:
            report.error("$timelineMigration", f"expected phase-two value {expected!r}, got {actual!r}", card_id)

    endpoint_tuple = lambda endpoint: (
        endpoint.get("era"), endpoint.get("year"), endpoint.get("datePrecision"), endpoint.get("qualifier")
    ) if isinstance(endpoint, dict) else None
    for card_id in sorted(COMPOUND_PHASE_ONE_IDS & structured_ids):
        timeline = by_id[card_id].get("timeline")
        if not isinstance(timeline, dict):
            continue
        actual_parts = tuple(
            (
                part.get("key"), part.get("label"), part.get("role"), endpoint_tuple(part.get("start")),
                endpoint_tuple(part.get("end")) if part.get("role") == "segment" else None,
            )
            for part in timeline.get("parts", []) if isinstance(part, dict)
        )
        actual = (timeline.get("defaultPart"), actual_parts)
        expected = COMPOUND_PHASE_ONE_EXPECTED[card_id]
        if timeline.get("kind") != "compound" or actual != expected:
            report.error("$timelineMigration", f"expected compound value {expected!r}, got {actual!r}", card_id)

    for card_id, (time_text, kind, start, end) in LEGACY_CE_GOLDEN.items():
        card = by_id.get(card_id)
        if card is None:
            report.error("$timelineGolden", "missing golden CE card", card_id)
            continue
        if card.get("timeText") != time_text:
            report.error("$timelineGolden", f"timeText changed; expected {time_text!r}", card_id)
        if "timelineInclude" in card or "timeline" in card:
            report.error("$timelineGolden", "golden CE card must remain on legacy inference", card_id)
        actual = legacy_ce_snapshot(card.get("timeText", ""))
        if actual != (kind, start, end):
            report.error("$timelineGolden", f"legacy snapshot changed: {actual!r}", card_id)


def legacy_ce_snapshot(time_text: str) -> tuple[str, str, str | None] | None:
    """Small executable golden for the legacy patterns represented above."""
    value = time_text.replace("－", "—").replace("–", "—")
    month_range = re.search(r"(\d{1,4})年\s*(\d{1,2})月?\s*(?:至|到|—|-)\s*(\d{1,2})月", value)
    if month_range:
        year, start_month, end_month = map(int, month_range.groups())
        return (
            "range",
            f"{year:04d}-{start_month:02d}-15",
            f"{year:04d}-{end_month:02d}-{calendar.monthrange(year, end_month)[1]:02d}",
        )
    year_range = re.search(r"(\d{1,4})\s*(?:年)?\s*(?:至|到|—|-)\s*(\d{1,4})年", value)
    if year_range:
        start_year, end_year = map(int, year_range.groups())
        return "range", f"{start_year:04d}-06-30", f"{end_year:04d}-12-31"
    full_date = re.search(r"(\d{1,4})年\s*(\d{1,2})月\s*(\d{1,2})日", value)
    if full_date:
        year, month, day = map(int, full_date.groups())
        return "point", f"{year:04d}-{month:02d}-{day:02d}", None
    return None


def validate(data: Any, report: ValidationReport) -> None:
    if not validate_exact_keys(data, TOP_LEVEL_KEYS, "$", report):
        return

    schema_version = data.get("schemaVersion")
    if type(schema_version) is not int or schema_version != 2:
        report.error(
            "$.schemaVersion",
            f"expected integer 2, got {schema_version!r}",
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
    validate_timeline_migration(by_id, report)


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
