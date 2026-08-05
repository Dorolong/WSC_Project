import dataclasses

import numpy as np

from Configs.Vehicle_Params import build_default_cfg


CFG_SECTION_NAMES = ("physics", "solar", "cell", "pack", "power", "drive", "race", "simpara")


def cfg_to_jsonable(cfg):
    """Convert a cfg namespace into JSON-safe primitives."""

    def convert(value):
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, np.ndarray):
            return value.tolist()
        return value

    return {
        name: convert(dataclasses.asdict(getattr(cfg, name)))
        for name in CFG_SECTION_NAMES
    }


def cfg_from_jsonable(data):
    """Restore a cfg namespace from a JSON-safe dict, preserving new default fields."""
    cfg = build_default_cfg()
    data = data or {}

    for name in ("physics", "solar", "power", "drive", "race", "simpara"):
        obj = getattr(cfg, name)
        for key, value in data.get(name, {}).items():
            if hasattr(obj, key):
                if name == "race" and key in ("Control_Stop_2025", "CS_open_hour", "CS_close_hour"):
                    value = {int(float(k)): v for k, v in value.items()}
                setattr(obj, key, value)

    for key, value in data.get("cell", {}).items():
        if hasattr(cfg.cell, key):
            setattr(cfg.cell, key, np.array(value) if key in ("ocv_soc", "ocv_V") else value)

    for key in ("HV_S", "HV_P", "LV_S", "LV_P"):
        if key in data.get("pack", {}):
            setattr(cfg.pack, key, data["pack"][key])

    cfg.pack.__post_init__()
    cfg.drive.__post_init__()
    return cfg
