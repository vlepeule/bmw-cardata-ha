#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
manifest_file="$repo_root/custom_components/cardata/manifest.json"

if [[ ! -f "$manifest_file" ]];
then
  echo "manifest.json not found at $manifest_file" >&2
  exit 1
fi

read -r old_version new_version < <(
  python3 - "$manifest_file" <<'PY'
import json
import pathlib
import re
import sys

manifest_path = pathlib.Path(sys.argv[1])
data = json.loads(manifest_path.read_text(encoding="utf-8"))
version = str(data.get("version", "0.0.0"))
numbers = [int(x) for x in re.findall(r"\d+", version)]
while len(numbers) < 3:
    numbers.append(0)
major, minor, patch = numbers[:3]
patch += 1
new_version = f"{major}.{minor}.{patch}"
data["version"] = new_version
manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(version, new_version)
PY
)

commit_message=${1:-"Release v$new_version"}

git -C "$repo_root" add .

if git -C "$repo_root" diff --cached --quiet; then
  echo "No changes staged. Nothing to commit." >&2
  exit 1
fi

git -C "$repo_root" commit -m "$commit_message"

tag_name="v$new_version"
git -C "$repo_root" tag -a "$tag_name" -m "$commit_message"

git -C "$repo_root" push
git -C "$repo_root" push origin "$tag_name"

echo "Bumped version $old_version -> $new_version and pushed tag $tag_name"
