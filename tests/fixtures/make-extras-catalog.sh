#!/bin/bash
# Builds an offline extras catalog in DIR (default: a new temp directory) and prints DIR:
#   registry/             files for a loopback npm registry on 127.0.0.1:48731
#   fixture/              catalog entry for agentainer-extra-fixture 1.0.0 (bin: fixture-extra)
#   fixture-v2/           the same entry pinned to 2.0.0
#   fixture-v3-mismatch/  pinned to 3.0.0; the tarball's own package.json says 3.0.1
#   fixture-check-fails/  the 1.0.0 entry with a check command that exits 1
#   fixture-stdin/        the 1.0.0 entry with a check that passes only when stdin has data
#   fixture-optional/     pinned to 4.0.0, which has an optional dependency on
#                         agentainer-extra-optional; omit_optional=no
#   fixture-omit/         the same with omit_optional=yes
#   fixture-two-bins/     pinned to 5.0.0, which has the bins fixture-extra and fixture-extra-two
#   fixture-bad/          the 1.0.0 lockfile, with the tarball URL moved to a copy whose
#                         bytes differ from the lockfile integrity
# Install from it while the registry runs:
#   python3 -m http.server --bind 127.0.0.1 --directory DIR/registry 48731
# Runs inside the image, so the extras tests need no network.
set -euo pipefail
port=48731
registry="http://127.0.0.1:$port/"
d=${1:-$(mktemp -d)}
mkdir -p "$d"
cd "$d"
mkdir -p registry/good registry/bad src

# pack VERSION INNER_VERSION MESSAGE DEST [EXTRA_JSON]: builds the fixture package tarball.
# EXTRA_JSON is added to its package.json, for example an optionalDependencies field.
pack() {
	rm -rf src/*
	printf '{"name":"agentainer-extra-fixture","version":"%s","bin":{"fixture-extra":"cli.js"}%s}\n' "$2" "${5:+,$5}" >src/package.json
	printf '#!/usr/bin/env node\nconsole.log("%s")\n' "$3" >src/cli.js
	(cd src && npm pack --silent >/dev/null)
	mv "src/agentainer-extra-fixture-$2.tgz" "$4"
}
optional='"optionalDependencies":{"agentainer-extra-optional":"1.0.0"}'
pack 1.0.0 1.0.0 "fixture-extra ok 1.0.0" registry/good/agentainer-extra-fixture-1.0.0.tgz
pack 2.0.0 2.0.0 "fixture-extra ok 2.0.0" registry/good/agentainer-extra-fixture-2.0.0.tgz
pack 3.0.0 3.0.1 "fixture-extra ok 3.0.1" registry/good/agentainer-extra-fixture-3.0.0.tgz
pack 4.0.0 4.0.0 "fixture-extra ok 4.0.0" registry/good/agentainer-extra-fixture-4.0.0.tgz "$optional"
pack 1.0.0 1.0.0 "fixture-extra changed bytes" registry/bad/agentainer-extra-fixture-1.0.0.tgz
rm -rf src/*
printf '{"name":"agentainer-extra-fixture","version":"5.0.0","bin":{"fixture-extra":"cli.js","fixture-extra-two":"two.js"}}\n' >src/package.json
printf '#!/usr/bin/env node\nconsole.log("fixture-extra ok 5.0.0")\n' >src/cli.js
printf '#!/usr/bin/env node\nconsole.log("fixture-extra-two ok 5.0.0")\n' >src/two.js
(cd src && npm pack --silent >/dev/null)
mv src/agentainer-extra-fixture-5.0.0.tgz registry/good/
rm -rf src/*
printf '{"name":"agentainer-extra-optional","version":"1.0.0"}\n' >src/package.json
(cd src && npm pack --silent >/dev/null)
mv src/agentainer-extra-optional-1.0.0.tgz registry/good/
rm -rf src

# Each packument lists its versions with the integrity of the tarballs in good/.
python3 - "$registry" <<'EOF'
import base64
import hashlib
import json
import sys

base = sys.argv[1]


def manifest(name, version, extra):
    data = open("registry/good/%s-%s.tgz" % (name, version), "rb").read()
    doc = {
        "name": name,
        "version": version,
        "dist": {
            "tarball": base + "good/%s-%s.tgz" % (name, version),
            "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
            "shasum": hashlib.sha1(data).hexdigest(),
        },
    }
    doc.update(extra)
    return doc


def packument(name, versions):
    doc = {"name": name, "dist-tags": {"latest": max(versions)}, "versions": versions}
    with open("registry/" + name, "w") as f:
        json.dump(doc, f)


bin_ = {"bin": {"fixture-extra": "cli.js"}}
two_bins = {"bin": {"fixture-extra": "cli.js", "fixture-extra-two": "two.js"}}
opt = {"optionalDependencies": {"agentainer-extra-optional": "1.0.0"}}
name = "agentainer-extra-fixture"
packument(name, {
    "1.0.0": manifest(name, "1.0.0", bin_),
    "2.0.0": manifest(name, "2.0.0", bin_),
    "3.0.0": manifest(name, "3.0.0", bin_),
    "4.0.0": manifest(name, "4.0.0", dict(bin_, **opt)),
    "5.0.0": manifest(name, "5.0.0", two_bins),
})
packument("agentainer-extra-optional", {"1.0.0": manifest("agentainer-extra-optional", "1.0.0", {})})
EOF

python3 -m http.server --bind 127.0.0.1 --directory registry "$port" >/dev/null 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null || true; rm -rf "$d/cache"' EXIT
for _ in $(seq 50); do
	curl -sf "${registry}agentainer-extra-fixture" >/dev/null 2>&1 && break
	sleep 0.1
done

# entry NAME VERSION CHECK [OMIT_OPTIONAL] [BINS]: writes a catalog entry and generates its lockfile.
entry() {
	mkdir -p "$1"
	printf '{"private":true,"dependencies":{"agentainer-extra-fixture":"%s"}}\n' "$2" >"$1/package.json"
	(cd "$1" && npm install --package-lock-only --ignore-scripts --no-audit --no-fund \
		--registry "$registry" --cache "$d/cache" >/dev/null)
	cat >"$1/extra.conf" <<EOC
package=agentainer-extra-fixture
description="Offline test fixture"
bins="${5:-fixture-extra}"
omit_optional=${4:-no}
check='$3'
notes="fixture notes: run fixture-extra"
EOC
}
entry fixture 1.0.0 'test -x node_modules/.bin/fixture-extra'
entry fixture-v2 2.0.0 'test -x node_modules/.bin/fixture-extra'
entry fixture-v3-mismatch 3.0.0 'test -x node_modules/.bin/fixture-extra'
entry fixture-check-fails 1.0.0 'exit 1'
entry fixture-stdin 1.0.0 'read -r x'
entry fixture-optional 4.0.0 'test -x node_modules/.bin/fixture-extra'
entry fixture-omit 4.0.0 'test -x node_modules/.bin/fixture-extra' yes
entry fixture-two-bins 5.0.0 'test -x node_modules/.bin/fixture-extra-two' no "fixture-extra fixture-extra-two"
mkdir fixture-bad
cp fixture/package.json fixture/extra.conf fixture-bad/
sed 's#/good/#/bad/#' fixture/package-lock.json >fixture-bad/package-lock.json
echo "$d"
