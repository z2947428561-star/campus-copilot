"""Read the supplied community XLSX into a local-only seed (stdlib, no Excel needed)."""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/structured/seed_course_recommendations.local.json"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
CATEGORIES = {"Art", "Business", "Science"}
TEACHER_SECTIONS = {"老师避雷", "老师推荐", "老师询问"}


def read_rows(path: Path):
    """Read actual XML rows, not the workbook's sometimes incorrect dimension hint."""
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(t.text or "" for t in item.findall(".//s:t", NS))
                for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
        relationships = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            if rel.attrib.get("TargetMode") != "External"
        }
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        for sheet in book.find("s:sheets", NS):
            target = relationships[sheet.attrib[REL_ID]]
            target = (target.lstrip("/") if target.startswith("/")
                      else posixpath.normpath("xl/" + target))
            root = ET.fromstring(archive.read(target))
            for row in root.findall("s:sheetData/s:row", NS):
                cells = {}
                for cell in row.findall("s:c", NS):
                    if cell.find("s:f", NS) is not None:
                        raise ValueError("源表含公式，需先核对计算结果，不能把缓存当原文导入")
                    value = cell.find("s:v", NS)
                    text = value.text or "" if value is not None else ""
                    if cell.attrib.get("t") == "s":
                        text = strings[int(text)] if text else ""
                    elif cell.attrib.get("t") == "inlineStr":
                        text = "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                    if text.strip():
                        cells[cell.attrib["r"]] = text.strip()
                if cells:
                    yield sheet.attrib["name"], int(row.attrib["r"]), cells


def extract_seed(path: Path) -> dict:
    records = []
    category = section = subsection = ""
    headers = {}
    current_sheet = None
    for sheet, row, cells in read_rows(path):
        if sheet != current_sheet:
            category = section = subsection = ""
            headers = {}
            current_sheet = sheet
        columns = {re.sub(r"\d+$", "", key): value for key, value in cells.items()}
        heading = columns.get("A", "")
        if heading in CATEGORIES:
            category, section, subsection, headers = heading, "courses", "", {}
            continue
        if heading in TEACHER_SECTIONS:
            category, section, subsection, headers = "", "teachers", heading, {}
            continue
        if heading.startswith("选课常见问题"):
            category, section, subsection, headers = "", "faq", heading, {}
            continue
        if heading == "新设课程":
            subsection = heading
            continue
        if heading == "课程名称" or columns.get("B") in {"老师名字", "问题"}:
            headers = columns
            continue
        if not section:
            continue  # workbook title and contributor notice, not course evidence
        title = columns.get("A" if section == "courses" else "B", "")
        record_id = hashlib.sha256(f"{sheet}:{row}".encode()).hexdigest()[:16]
        records.append({
            "id": record_id, "section": section, "category": category,
            "subsection": subsection, "title": title,
            "attribution": "named_row" if title else "unassigned_row",
            "source_sheet": sheet, "source_row": row,
            "cells": [{"cell": key, "header": headers.get(re.sub(r"\d+$", "", key), ""),
                       "text": value} for key, value in cells.items()],
        })
    if not records:
        raise ValueError("未识别到课程/教师/问答分区，请检查源表结构")
    return {
        "schema_version": 1,
        "source": {"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "type": "community_opinions", "official": False, "as_of": None},
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true", help="replace an existing local seed")
    args = parser.parse_args()
    if not args.output.name.endswith(".local.json"):
        parser.error("输出必须以 .local.json 结尾，防止误提交原始评价")
    if args.output.exists() and not args.replace:
        parser.error("输出已存在；核对文件后加 --replace 更新")
    data = extract_seed(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Extraction is deterministic; never rewrite the original workbook.
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成本机种子：{len(data['records'])} 条原始行，未上传外部服务。")


if __name__ == "__main__":
    main()
