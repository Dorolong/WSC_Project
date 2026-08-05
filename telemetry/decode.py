"""Pure CAN telemetry decoders used by offline uploads and future UDP input."""

from __future__ import annotations

import csv
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class DecodedFrame:
    can_id: str
    raw_data_hex: str
    dlc: int
    seg_one: float | None
    seg_two: float | None
    timestamp: str | None = None
    bus_id: str | None = None
    client_id: str | None = None
    flags: int | None = None


def normalize_can_id(value) -> str:
    if isinstance(value, int):
        return f"0x{value:03X}"
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower().startswith("0x"):
        try:
            return f"0x{int(text, 16):03X}"
        except ValueError:
            return text.upper()
    try:
        return f"0x{int(text):03X}"
    except ValueError:
        return text.upper()


def decode_canlog_data_hex(value: str) -> bytes:
    """Return the original eight CAN data bytes from a canlog.csv data cell.

    The log tool prints the 8-byte payload reversed. The project decoder spec
    therefore reverses the printed bytes before applying any signal decoding.
    """

    text = str(value or "").strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    text = "".join(text.split())
    if len(text) % 2:
        raise ValueError("CAN data hex must contain whole bytes.")
    data = bytes.fromhex(text)
    return data[::-1]


def data_segments(data: bytes) -> tuple[float | None, float | None]:
    if len(data) < 8:
        return None, None
    return struct.unpack("<f", data[0:4])[0], struct.unpack("<f", data[4:8])[0]


def decode_frame(
    can_id,
    data: bytes,
    *,
    timestamp: str | None = None,
    bus_id: str | None = None,
    client_id: str | None = None,
    flags: int | None = None,
) -> DecodedFrame:
    raw = bytes(data)
    seg_one, seg_two = data_segments(raw)
    return DecodedFrame(
        can_id=normalize_can_id(can_id),
        raw_data_hex=raw.hex().upper(),
        dlc=len(raw),
        seg_one=seg_one,
        seg_two=seg_two,
        timestamp=timestamp,
        bus_id=bus_id,
        client_id=client_id,
        flags=flags,
    )


def parse_udp_packet(payload: bytes) -> list[DecodedFrame]:
    """Parse a raw UDP payload into CAN frames.

    Phase 1 does not open a UDP socket. This pure parser is kept here so Phase 2
    can attach a receiver without duplicating frame decoding.
    """

    if len(payload) < 16:
        raise ValueError("UDP payload is shorter than the 16-byte header.")

    bus_id = payload[1:8].hex().upper()
    client_id = payload[9:16].hex().upper()
    frames: list[DecodedFrame] = []
    offset = 16
    while offset < len(payload):
        if offset + 6 > len(payload):
            raise ValueError("Truncated CAN frame header in UDP payload.")
        can_id = int.from_bytes(payload[offset : offset + 4], "little")
        flags = payload[offset + 4]
        dlc = payload[offset + 5]
        offset += 6
        if dlc > 8:
            raise ValueError(f"Invalid CAN data length: {dlc}")
        if offset + dlc > len(payload):
            raise ValueError("Truncated CAN data in UDP payload.")
        data = payload[offset : offset + dlc]
        offset += dlc
        frames.append(decode_frame(can_id, data, bus_id=bus_id, client_id=client_id, flags=flags))
    return frames


def _header_index(header: list[str], names: Iterable[str], fallback: int | None = None) -> int | None:
    lowered = [h.strip().lower() for h in header]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    return fallback if fallback is not None and fallback < len(header) else None


def _looks_like_header(row: list[str]) -> bool:
    joined = " ".join(cell.strip().lower() for cell in row)
    return "data" in joined and ("can" in joined or "id" in joined)


def parse_canlog_csv(path: str | Path) -> Iterator[DecodedFrame]:
    """Stream frames from canlog.csv without loading the whole file."""

    with Path(path).open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        header: list[str] | None = None
        indexes = {"time": 0, "id": 3, "data": 4}
        for row in reader:
            if not row:
                continue
            if header is None and _looks_like_header(row):
                header = row
                indexes["time"] = _header_index(header, ("time", "timestamp", "date time"), 0)
                indexes["id"] = _header_index(header, ("can id", "id", "identifier"), 3)
                indexes["data"] = _header_index(header, ("data", "data bytes"), 4)
                continue
            data_idx = indexes.get("data")
            if data_idx is None or data_idx >= len(row):
                continue
            data_cell = row[data_idx].strip()
            if not data_cell.lower().startswith("0x"):
                continue
            try:
                data = decode_canlog_data_hex(data_cell)
            except ValueError:
                continue
            time_idx = indexes.get("time")
            id_idx = indexes.get("id")
            timestamp = row[time_idx].strip() if time_idx is not None and time_idx < len(row) else None
            can_id = row[id_idx].strip() if id_idx is not None and id_idx < len(row) else ""
            yield decode_frame(can_id, data, timestamp=timestamp)


def close_float(a: float, b: float, rel_tol: float = 2e-6) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if a == b:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0:
        return abs(a - b) < 1e-30
    return abs(a - b) / denom < rel_tol
