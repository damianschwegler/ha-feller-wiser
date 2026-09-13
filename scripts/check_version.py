"""Fail unless custom_components/feller_wiser/manifest.json version equals the given tag."""

import json
import pathlib
import sys

expected = sys.argv[1]
manifest = json.loads(
    pathlib.Path("custom_components/feller_wiser/manifest.json").read_text(encoding="utf-8")
)
if manifest["version"] != expected:
    print(f"manifest version {manifest['version']} != tag {expected}")
    sys.exit(1)
print(f"version {expected} ok")
