#!/usr/bin/env python3
"""Markdown sections for the CI job summary.

  build_report.py versions VERSIONS.json     pinned versions, key apt packages and extras pins
  build_report.py pins OLD.env NEW.env       versions.env lines that changed (empty if none)
  build_report.py major OLD.env NEW.env      major-version review notice (empty if none)
  build_report.py layers TOTAL_BYTES         image size and largest layers; reads
                                             `docker history --human=false --no-trunc
                                             --format '{{.Size}}\t{{.CreatedBy}}'` on stdin
  build_report.py tests LABEL LOG            pass and fail counts per test file, from
                                             the TAP output of tests/run.sh
"""
import json
import os
import re
import sys

KEY_APT = ("bash", "git", "python3", "tmux")
MAX_LAYERS = 10
MAX_COMMAND = 120
MiB = 1024 * 1024


UNITS = {"": 1, "b": 1, "kb": 1000, "k": 1000, "mb": 1000 ** 2, "m": 1000 ** 2,
         "gb": 1000 ** 3, "g": 1000 ** 3, "tb": 1000 ** 4}


def parse_size(text):
    """Bytes from "12345", "0 B" or "1.5 GB". go-units, which Docker and Podman use, is decimal."""
    m = re.fullmatch(r"\s*([0-9.]+)\s*([A-Za-z]*)\s*", text)
    if not m or m.group(2).lower() not in UNITS:
        raise ValueError(text)
    return int(float(m.group(1)) * UNITS[m.group(2).lower()])


def cell(text):
    return str(text).replace("|", "\\|")


def short(value):
    # Checksums and digests are long; the first 12 characters identify them in a review.
    if re.fullmatch(r"[0-9a-f]{40,}", value):
        return value[:12] + "..."
    return re.sub(r"(sha256:[0-9a-f]{12})[0-9a-f]+", r"\1...", value)


def extra_names():
    """versions.env key to catalog name for each optional extra, from bump_versions.EXTRAS."""
    # Only the versions mode may call this. The bump-pr action runs the major mode from a
    # standalone copy of this file, where bump_versions and its imports are not importable.
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import bump_versions
    return {key: extra for key, _package, extra in bump_versions.EXTRAS}


def versions(path):
    with open(path) as f:
        data = json.load(f)
    pins, apt = data.get("pins", {}), data.get("apt", {})
    extras = extra_names()
    lines = ["### Versions in this build", "", "| Component | Version |", "|---|---|"]
    for key in sorted(pins):
        if key.endswith("_VERSION") and key not in extras:
            name = key[:-len("_VERSION")].lower().replace("_", "-")
            lines.append("| %s | %s |" % (cell(name), cell(pins[key])))
    for name in KEY_APT:
        if name in apt:
            lines.append("| %s (apt) | %s |" % (name, cell(apt[name])))
    lines += ["", "Base image: `%s`. apt snapshot: `%s`. %d apt packages; the full list is in "
              "`/etc/agentainer/versions.json` in the image." % (
                  short(pins.get("BASE_IMAGE", "?")), pins.get("APT_SNAPSHOT", "?"), len(apt))]
    # Extras are pinned in the image's catalog but installed only by agentainer-extras install.
    listed = sorted((extras[key], pins[key]) for key in pins if key in extras)
    if listed:
        lines += ["", "### Optional extras (not installed)", "", "| Extra | Pinned version |", "|---|---|"]
        lines += ["| %s | %s |" % (cell(name), cell(version)) for name, version in listed]
        lines += ["", "Install one in a container with `agentainer-extras install NAME`."]
    return "\n".join(lines) + "\n\n"


def read_env(path):
    pins = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    pins[k] = v
    except FileNotFoundError:
        pass
    return pins


def pins(old_path, new_path):
    old, new = read_env(old_path), read_env(new_path)
    changed = [k for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
    if not changed:
        return ""
    lines = ["### Pins changed", "", "| Pin | Before | After |", "|---|---|---|"]
    for k in changed:
        lines.append("| %s | %s | %s |" % (
            cell(k), cell(short(old[k])) if k in old else "(none)", cell(short(new[k])) if k in new else "(none)"))
    return "\n".join(lines) + "\n\n"


def major_updates(old_path, new_path):
    """Ask for review when a version's leading number increases."""
    old, new = read_env(old_path), read_env(new_path)
    rows = []
    for key in sorted(set(old) & set(new)):
        if not key.endswith("_VERSION"):
            continue
        before = re.fullmatch(r"v?([0-9]+)\.[0-9]+\.[0-9]+(?:[-+].*)?", old[key])
        after = re.fullmatch(r"v?([0-9]+)\.[0-9]+\.[0-9]+(?:[-+].*)?", new[key])
        if before and after and int(after[1]) > int(before[1]):
            rows.append("| %s | %s | %s |" % (key, cell(old[key]), cell(new[key])))
    if not rows:
        return ""
    return "\n".join([
        "### Major-version upgrades", "",
        "Review upstream compatibility and migration notes before merging.", "",
        "| Pin | Before | After |", "|---|---|---|", *rows, "",
        "- [ ] I reviewed and accept these major-version upgrades.", "",
        "This acknowledgement records maintainer review; CI does not enforce the checkbox.", "",
    ]) + "\n"


def layers(stream, total):
    rows = []
    for line in stream:
        size, _, command = line.rstrip("\n").partition("\t")
        try:
            size = parse_size(size)
        except ValueError:
            continue
        if size > 0:
            command = " ".join(command.split())
            # "|4 A=1 B=2 /bin/sh -c #(nop) X" is the build-arg prefix and shell; keep X.
            command = re.sub(r"^\|\d+ (\S+=\S* )*", "", command)
            command = re.sub(r"^/bin/sh -c (#\(nop\) )?", "", command)
            if len(command) > MAX_COMMAND:
                command = command[:MAX_COMMAND] + "..."
            rows.append((size, command))
    rows.sort(key=lambda r: -r[0])
    lines = ["### Image size", "", "Image size: %.1f MiB." % (total / MiB), "",
             "| Layer size | Created by |", "|---|---|"]
    for size, command in rows[:MAX_LAYERS]:
        lines.append("| %.1f MiB | %s |" % (size / MiB, cell(command)))
    return "\n".join(lines) + "\n\n"


def tests(label, path):
    files, failures, current = [], [], None
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            m = re.match(r"# (tests/\S+)$", line)
            if m:
                current = [m.group(1), 0, 0]
                files.append(current)
                continue
            if current is None:
                continue
            # TAP makes the test number optional; tests/run.sh omits it on the line it adds
            # for a file that exits non-zero without a failing test.
            m = re.match(r"(not )?ok(?: \d+)? - (.*)$", line)
            if m:
                if m.group(1):
                    current[2] += 1
                    failures.append("%s: %s" % (current[0], m.group(2)))
                else:
                    current[1] += 1
    lines = ["### Container tests (%s)" % label, "", "| File | Passed | Failed |", "|---|---|---|"]
    for name, ok, bad in files:
        lines.append("| %s | %d | %d |" % (name, ok, bad))
    lines.append("| Total | %d | %d |" % (sum(r[1] for r in files), sum(r[2] for r in files)))
    if failures:
        lines += ["", "Failed:", ""] + ["- %s" % cell(x) for x in failures]
    return "\n".join(lines) + "\n\n"


def main(argv):
    try:
        cmd, args = argv[0], argv[1:]
        if cmd == "versions" and len(args) == 1:
            out = versions(args[0])
        elif cmd == "pins" and len(args) == 2:
            out = pins(args[0], args[1])
        elif cmd == "major" and len(args) == 2:
            out = major_updates(args[0], args[1])
        elif cmd == "layers" and len(args) == 1:
            out = layers(sys.stdin, int(args[0]))
        elif cmd == "tests" and len(args) == 2:
            out = tests(args[0], args[1])
        else:
            raise IndexError
    except (IndexError, ValueError):
        print(__doc__, file=sys.stderr)
        return 2
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
