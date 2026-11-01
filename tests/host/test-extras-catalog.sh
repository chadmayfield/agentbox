#!/bin/sh
# Checks the extras catalog in rootfs/usr/local/share/agentainer/extras offline: each pin in
# versions.env equals its wrapper package.json, the wrapper is formatted as
# scripts/bump_versions.py writes it, each lockfile is npm lockfileVersion 3 with an integrity
# on every downloaded package, and install scripts appear only in allowlisted packages.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
cd "$(dirname "$0")/../.." || exit 2
# checker prints one "ok<TAB>name" or "FAIL<TAB>name<TAB>detail" line per check.
checker() {
	python3 -I - "$PWD" <<'EOF'
import json
import os
import subprocess
import sys

repo = sys.argv[1]
sys.path.insert(0, os.path.join(repo, "scripts"))
import bump_versions  # noqa: E402

# Packages whose lockfile entries may carry hasInstallScript. Extras install with
# npm ci --ignore-scripts, so these scripts never run. node-pty is an @openchamber/web
# dependency and frida a rea-agents optional dependency; both declare scripts.install in
# their registry metadata (https://registry.npmjs.org/node-pty/1.2.0-beta.15,
# https://registry.npmjs.org/frida/17.23.2).
ALLOWED = {"node-pty", "frida"}
REGISTRY = "https://registry.npmjs.org/"
EXPECTED = {
    "kandev": ("kandev", "no"),
    "openchamber": ("@openchamber/web", "no"),
    "rea": ("rea-agents", "no"),
}


def say(ok, name, detail=""):
    # One line per check: the shell side reads tab-separated fields line by line.
    detail = " ".join(str(detail).split())
    print(("ok" if ok else "FAIL") + "\t" + name + ("\t" + detail if detail and not ok else ""))


say(bump_versions.INSTALL_SCRIPT_ALLOWLIST == frozenset(ALLOWED),
    "the bump allowlist names the same install-script packages as this test",
    "bump_versions has %s" % sorted(bump_versions.INSTALL_SCRIPT_ALLOWLIST))

pins = {}
with open(os.path.join(repo, "versions.env")) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            pins[k] = v

catalog = os.path.join(repo, bump_versions.EXTRAS_DIR)
names = sorted(d for d in os.listdir(catalog)) if os.path.isdir(catalog) else []
say(names == sorted(EXPECTED), "the catalog holds kandev, openchamber and rea", "got %s" % names)
say(sorted(e[2] for e in bump_versions.EXTRAS) == sorted(EXPECTED),
    "bump_versions.EXTRAS lists the same catalog entries")

for key, package, extra in bump_versions.EXTRAS:
    d = os.path.join(catalog, extra)
    missing = [f for f in ("package.json", "package-lock.json", "extra.conf")
               if not os.path.isfile(os.path.join(d, f))]
    say(not missing, "%s has package.json, package-lock.json and extra.conf" % extra, "missing %s" % missing)
    if missing:
        continue
    with open(os.path.join(d, "package.json")) as f:
        text = f.read()
    wrapper = json.loads(text)
    say(text == json.dumps(wrapper, indent=2) + "\n",
        "%s/package.json is formatted as json.dumps(indent=2) plus a newline" % extra)
    deps = wrapper.get("dependencies") or {}
    say(list(deps) == [package], "%s/package.json depends on exactly %s" % (extra, package), "got %s" % list(deps))
    pin = pins.get(key)
    say(pin is not None and deps.get(package) == pin, "%s in versions.env equals the %s wrapper version" % (key, extra),
        "versions.env %s, package.json %s" % (pin, deps.get(package)))

    # extra.conf is read the way agentainer-extras reads it: sourced in a child shell.
    conf = subprocess.run(["sh", "-c", '. "$1" && printf "%s\\n" "$package" "$omit_optional" "$bins"', "sh",
                           os.path.join(d, "extra.conf")], capture_output=True, text=True)
    lines = conf.stdout.split("\n")
    conf_ok = conf.returncode == 0 and len(lines) >= 3
    say(conf_ok and lines[0] == package, "%s/extra.conf names package %s" % (extra, package), conf.stdout + conf.stderr)
    say(conf_ok and lines[1] == EXPECTED[extra][1],
        "%s/extra.conf sets omit_optional=%s" % (extra, EXPECTED[extra][1]), conf.stdout)

    with open(os.path.join(d, "package-lock.json")) as f:
        lock = json.load(f)
    say(lock.get("lockfileVersion") == 3, "%s lockfile has lockfileVersion 3" % extra, str(lock.get("lockfileVersion")))
    packages = lock.get("packages") or {}
    say((packages.get("") or {}).get("dependencies") == deps,
        "%s lockfile root depends on the wrapper's pin" % extra)
    top = packages.get("node_modules/" + package) or {}
    say(top.get("version") == pin, "%s lockfile holds %s@%s" % (extra, package, pin), "got %s" % top.get("version"))
    bins = lines[2].split() if conf_ok else []
    declared = top.get("bin") or {}
    say(bool(bins) and all(b in declared for b in bins),
        "%s/extra.conf bins %s are declared by %s" % (extra, bins, package), "package declares %s" % sorted(declared))

    entries = [(p, e) for p, e in packages.items() if p]
    # Bundled entries ship inside their parent's tarball and have no integrity of their own.
    no_integrity = [p for p, e in entries if not e.get("inBundle") and not e.get("integrity")]
    say(bool(entries) and not no_integrity, "%s lockfile has an integrity on every package (%d)" % (extra, len(entries)),
        "missing on %s" % no_integrity[:5])
    links = [p for p, e in entries if e.get("link")]
    say(not links, "%s lockfile has no link entries" % extra, str(links))
    elsewhere = [p for p, e in entries
                 if not e.get("inBundle") and not str(e.get("resolved", "")).startswith(REGISTRY)]
    say(bool(entries) and not elsewhere,
        "%s lockfile resolves every package from %s" % (extra, REGISTRY),
        "elsewhere: %s" % elsewhere[:5])
    scripts = sorted({bump_versions.lock_entry_name(p, e) for p, e in entries if e.get("hasInstallScript")})
    say(not set(scripts) - ALLOWED, "%s lockfile has install scripts only in %s" % (extra, sorted(ALLOWED)),
        "found %s" % scripts)
EOF
}
if ! out=$(checker); then
	fail "catalog checker runs" "python3 exited non-zero: $out"
	finish
	exit 1
fi
pass "catalog checker runs"
tab=$(printf '\t')
while IFS="$tab" read -r result name detail; do
	if [ "$result" = ok ]; then pass "$name"; else fail "$name" "$detail"; fi
done <<EOF
$out
EOF
finish
