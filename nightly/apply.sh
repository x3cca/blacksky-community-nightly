#!/usr/bin/env bash
# Turn a clean upstream checkout into the Blacksky Nightly variant.
# Usage: nightly/apply.sh <upstream-checkout>
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
app="$(cd "$1" && pwd)"

# Expo config: keep upstream's, wrap it with our overrides.
mv "$app/app.config.js" "$app/app.config.upstream.js"
cp "$here/app.config.js" "$app/app.config.js"
mkdir -p "$app/nightly"
cp "$here"/*.png "$app/nightly/"

# Placeholder Firebase config for our package ID.
node -e '
  const fs = require("fs"), [src, dst] = process.argv.slice(1)
  const j = JSON.parse(fs.readFileSync(src, "utf8"))
  for (const c of j.client) c.client_info.android_client_info.package_name = "community.blacksky.app.nightly"
  fs.writeFileSync(dst, JSON.stringify(j, null, 2))
' "$app/google-services.json.example" "$app/google-services.json"

# Android can't bundle foo.png and foo.webp from the same folder (duplicate
# resource). When upstream ships both, point code imports at the .webp.
cd "$app"
git ls-files -- 'assets/*.png' | while read -r png; do
  [ -f "${png%.png}.webp" ] || continue
  name="$(basename "$png" .png)"
  grep -rlE "/${name}\.png['\"]" src | while read -r file; do
    sed -i -E "s#/${name}\.png(['\"])#/${name}.webp\1#g" "$file"
    echo "nightly: $file now imports ${name}.webp instead of ${name}.png"
  done
done
