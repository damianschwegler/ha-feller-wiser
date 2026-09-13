"""Fail if translations/de.json and en.json (or strings.json) differ in their key sets."""

import json
import pathlib
import sys

BASE = pathlib.Path("custom_components/feller_wiser")


def keys(obj: object, prefix: str = "") -> set[str]:
    if isinstance(obj, dict):
        out: set[str] = set()
        for key, value in obj.items():
            out |= keys(value, f"{prefix}{key}.")
        return out
    return {prefix.rstrip(".")}


strings = json.loads((BASE / "strings.json").read_text(encoding="utf-8"))
en = json.loads((BASE / "translations" / "en.json").read_text(encoding="utf-8"))
de = json.loads((BASE / "translations" / "de.json").read_text(encoding="utf-8"))
ok = True
for name, data in (("en.json", en), ("de.json", de)):
    missing = keys(strings) - keys(data)
    extra = keys(data) - keys(strings)
    if missing or extra:
        ok = False
        print(f"{name}: missing {sorted(missing)} extra {sorted(extra)}")
print("translations ok" if ok else "translations differ")
sys.exit(0 if ok else 1)
