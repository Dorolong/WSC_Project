"""Convert the read-only CAN spreadsheet into specs/can_signals.csv.

The source workbook contains drawings/images, so this script reads the XLSX as
ZIP/XML and never saves it back through an Excel library.
"""

from __future__ import annotations

import csv
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch.upper()) - ord("A") + 1
    return value - 1


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for item in root.findall("m:si", NS):
        strings.append("".join(text.text or "" for text in item.findall(".//m:t", NS)))
    return strings


def _sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("r:Relationship", REL_NS)}
    paths = {}
    for sheet in workbook.find("m:sheets", NS):
        rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rel_map[rel_id]
        paths[sheet.attrib["name"]] = "xl/" + target.lstrip("/")
    return paths


def _read_sheet(zf: zipfile.ZipFile, shared: list[str], path: str) -> list[list[str]]:
    root = ET.fromstring(zf.read(path))
    rows = []
    for row_el in root.findall(".//m:row", NS):
        row = []
        for cell in row_el.findall("m:c", NS):
            idx = _col_index(cell.attrib.get("r", "A1"))
            while len(row) <= idx:
                row.append("")
            value = cell.find("m:v", NS)
            if value is None:
                inline = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
                row[idx] = inline.strip()
            elif cell.attrib.get("t") == "s":
                row[idx] = shared[int(value.text)].strip()
            else:
                row[idx] = (value.text or "").strip()
        rows.append(row)
    return rows


def _expand_can_ids(text: str) -> list[str]:
    text = text.strip()
    m = re.match(r"0x([0-9A-Fa-f]+)\s*[~-]\s*0x([0-9A-Fa-f]+)", text)
    if m:
        start, end = int(m.group(1), 16), int(m.group(2), 16)
        return [f"0x{i:03X}" for i in range(start, end + 1)]
    m = re.search(r"0x([0-9A-Fa-f]+)", text)
    if m:
        return [f"0x{int(m.group(1), 16):03X}"]
    return []


def _type_and_unit(type_text: str) -> tuple[str, str]:
    raw = type_text.strip()
    lower = raw.lower()
    signal_type = "float32" if "float" in lower else ""
    for candidate in ("u8", "u16", "u32", "i8", "i16", "i32"):
        if candidate in lower:
            signal_type = candidate
            break
    if "reserved" in lower:
        signal_type = "reserved"
    unit = ""
    for part in raw.split(",")[1:]:
        part = part.strip()
        if part and not re.fullmatch(r"[ui]\d+|float", part.lower()):
            unit = part
            break
    return signal_type or raw, unit


def _fields(text: str) -> tuple[list[dict], str]:
    fields = []
    note = ""
    for name, inside in re.findall(r"([^,()]+)\(([^()]*)\)", text):
        clean_name = name.strip()
        if not clean_name or "byte" in clean_name.lower():
            continue
        signal_type, unit = _type_and_unit(inside)
        fields.append({"name": clean_name, "type": signal_type, "unit": unit})
    if "Reserved" in text or "reserved" in text:
        note = "reserved bytes included"
    if len(fields) > 2:
        note = (note + "; " if note else "") + "확인 필요: 3개 이상 필드"
    return fields, note


def _row(priority, can_id, group, text, desc="", status="확정", note=""):
    fields, field_note = _fields(text)
    if field_note:
        note = (note + "; " if note else "") + field_note
    one = fields[0] if fields else {}
    two = fields[1] if len(fields) > 1 else {}
    name = one.get("name") or desc or text
    return {
        "can_id": can_id,
        "group": group,
        "priority": priority or "DETAIL",
        "name": name,
        "seg_one_field": one.get("name", ""),
        "seg_one_type": one.get("type", ""),
        "seg_one_unit": one.get("unit", ""),
        "seg_two_field": two.get("name", ""),
        "seg_two_type": two.get("type", ""),
        "seg_two_unit": two.get("unit", ""),
        "status": status,
        "note": note,
    }


def convert(xlsx_path: Path, csv_path: Path) -> list[dict]:
    rows_out = []
    mppt_by_offset = {}
    with zipfile.ZipFile(xlsx_path) as zf:
        shared = _shared_strings(zf)
        sheets = _sheet_paths(zf)
        for sheet_name in ("BMS(HV)", "MPPT", "Motor", "BMS(LV)"):
            rows = _read_sheet(zf, shared, sheets[sheet_name])
            for row in rows[1:]:
                padded = row + [""] * 6
                if sheet_name == "BMS(HV)":
                    target, priority, can_text, data_text, desc = padded[:5]
                    group = f"BMS(HV) {target}".strip()
                    status = "확정"
                    note = ""
                elif sheet_name == "MPPT":
                    priority, mppt_no, can_text, data_text, desc = padded[:5]
                    group = f"MPPT {mppt_no}".strip()
                    status = "확정"
                    note = ""
                    if priority == "PRIMARY" and data_text:
                        for cid in _expand_can_ids(can_text):
                            mppt_by_offset[int(cid, 16) & 0xF] = data_text
                    elif not data_text and mppt_no in {"#2", "#3"}:
                        ids = _expand_can_ids(can_text)
                        for cid in ids:
                            data_text = mppt_by_offset.get(int(cid, 16) & 0xF, "")
                            if data_text:
                                rows_out.append(_row("PRIMARY" if int(cid, 16) % 0x10 in (0, 1) else "DETAIL", cid, group, data_text, desc, status))
                        continue
                elif sheet_name == "Motor":
                    priority, can_text, data_text, desc = padded[:4]
                    group = "Motor"
                    status = "잠정"
                    note = "VCU 확정 전 WaveSculptor22 placeholder"
                else:
                    priority, can_text, data_text, desc = padded[:4]
                    group = "BMS(LV)"
                    status = "잠정"
                    note = "LV BMS 확정 전 OrionBMS placeholder"
                if not data_text:
                    continue
                for can_id in _expand_can_ids(can_text):
                    rows_out.append(_row(priority, can_id, group, data_text, desc, status, note))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)
    return rows_out


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    xlsx = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "specs" / "CAN_수신_데이터_정리본.xlsx"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "specs" / "can_signals.csv"
    rows = convert(xlsx, out)
    needs_check = [r for r in rows if r["status"] != "확정" or "확인 필요" in r["note"]]
    print(f"wrote {out} ({len(rows)} rows)")
    print(f"needs_check={len(needs_check)}")
    for row in needs_check[:80]:
        print(f"{row['can_id']} {row['group']} {row['name']} [{row['status']}] {row['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
