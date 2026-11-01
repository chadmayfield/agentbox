#!/usr/bin/env python3
"""Resolve the latest upstream pins and rewrite versions.env.

Every value comes from the upstream source named in its resolver. Any failure
stops the run and leaves the file unchanged. The extras resolver is the one
exception: a failed check for one extra keeps that extra's pin and catalog files,
the run continues, and --failures FILE lists the failed checks. Uses the Python
standard library, the publisher verification CLIs documented in docs/versions.md,
npm to generate extras lockfiles, and openssl to verify npm registry signatures.
"""
import argparse
import base64
import binascii
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import sys
import urllib.error
import urllib.parse
import urllib.request
from verify_upstream import VerificationFailed, verify_asset

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs/usr/local/lib/agentainer"))
from release_version import version_key

ARCHES = {"AMD64": "amd64", "ARM64": "arm64"}
# Manifest paths come from DOWNLOAD_BASE_URL and MANIFEST_URL in the official installer:
# https://antigravity.google/cli/install.sh
AGY_MANIFEST = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_{arch}.json"
AGY_KEYS = ("version", "url", "sha512")
AGY_HOST = "storage.googleapis.com"
AGY_BUCKET = "antigravity-public"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX128 = re.compile(r"^[0-9a-f]{128}$")


class LookupFailed(Exception):
    pass


# ---- versions.env handling -------------------------------------------------

# Shell scripts source versions.env and the build passes its values into RUN steps as
# root, so every value written must match a strict pattern for its key. Anything else, including an unknown key, is refused.
IMAGE_REF = r"[a-z0-9.-]+(:[0-9]+)?/[a-z0-9._/-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}"
VALUE_PATTERNS = [
    (r"(BASE_IMAGE|[A-Z0-9_]+_IMAGE)", IMAGE_REF),
    (r"APT_SNAPSHOT", r"[0-9]{8}T[0-9]{6}Z"),
    (r"SOURCE_DATE_EPOCH", r"[0-9]{1,12}"),
    (r"UNSLOP_COMMIT", r"[0-9a-f]{40}"),
    (r"[A-Z0-9_]+_VERSION", r"v?[0-9]+(\.[0-9]+)*([-+][0-9A-Za-z.-]+)?"),
    (r"[A-Z0-9_]+_SHA256(_[A-Z0-9]+)?", r"[0-9a-f]{64}"),
    (r"[A-Z0-9_]+_SHA512(_[A-Z0-9]+)?", r"[0-9a-f]{128}"),
    (r"[A-Z0-9_]+_INTEGRITY(_[A-Z0-9]+)?", r"sha512-[A-Za-z0-9+/]+={0,2}"),
    (r"AGY_URL_[A-Z0-9]+", r"https://storage\.googleapis\.com/antigravity-public/[A-Za-z0-9._/-]+"),
]


def agy_url_problem(url):
    """None when url names an object in the agy bucket, otherwise the reason.

    curl merges "/../" and "/./" in a URL path (see --path-as-is in curl(1)), and a
    server may decode percent escapes before it resolves the path, so a URL that
    starts with the bucket path can still reach another bucket. Only plain,
    non-empty segments with no escapes, query or fragment are accepted.
    """
    if any(c in url for c in "%?#\\"):
        return "agy url has a percent escape, query, fragment or backslash: %s" % url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.netloc != AGY_HOST:
        return "agy url is not https://%s: %s" % (AGY_HOST, url)
    segments = parts.path.split("/")
    if segments[:2] != ["", AGY_BUCKET] or len(segments) < 3:
        return "agy url is not in the %s bucket: %s" % (AGY_BUCKET, url)
    if any(seg in ("", ".", "..") for seg in segments[2:]):
        return "agy url has an empty, . or .. segment: %s" % url
    return None


def invalid(key, value):
    """None when value is safe to write for key, otherwise the reason."""
    for key_re, value_re in VALUE_PATTERNS:
        if re.fullmatch(key_re, key):
            if not re.fullmatch(value_re, value):
                return "%s=%r does not match %s" % (key, value, value_re)
            if key.startswith("AGY_URL_"):
                return agy_url_problem(value)
            return None
    return "%s is not a known pin" % key

def parse_env(text):
    """Return a list of (key or None, raw line)."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        out.append((m.group(1) if m else None, line))
    return out


def values(lines):
    return {k: raw.split("=", 1)[1] for k, raw in lines if k}


def render_env(lines, updates):
    seen = set()
    out = []
    for key, raw in lines:
        if key and key in updates:
            out.append("%s=%s" % (key, updates[key]))
            seen.add(key)
        else:
            out.append(raw)
    for key in updates:
        if key not in seen and key not in values(lines):
            out.append("%s=%s" % (key, updates[key]))
    return "\n".join(out) + "\n"


# ---- HTTP -----------------------------------------------------------------

class HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep downloads on HTTPS and credentials on the origin that received them.

    https://docs.python.org/3/library/urllib.request.html#urllib.request.HTTPRedirectHandler
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https":
            raise urllib.error.HTTPError(newurl, code, "redirect requires HTTPS", headers, fp)
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        origin = urllib.parse.urlsplit(req.full_url)
        if result is not None and (origin.hostname, origin.port or 443) != (target.hostname, target.port or 443):
            result.remove_header("Authorization")
        return result


def open_https(request):
    if urllib.parse.urlsplit(request.full_url).scheme != "https":
        raise LookupFailed("download requires HTTPS")
    return urllib.request.build_opener(HTTPSRedirectHandler()).open(request, timeout=60)

def fetch(url, accept=None):
    headers = {"User-Agent": "agentainer-bump"}
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + token
    try:
        with open_https(urllib.request.Request(url, headers=headers)) as r:
            return r.read().decode()
    except Exception as e:  # noqa: BLE001 - report any network error the same way
        raise LookupFailed("%s: %s" % (url, e))


def fetch_bytes(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agentainer-bump"})
        with open_https(req) as r:
            return r.read()
    except Exception as e:  # noqa: BLE001 - report any network error the same way
        raise LookupFailed("%s: %s" % (url, e))


def fetch_json(url):
    try:
        return json.loads(fetch(url, "application/json"))
    except ValueError as e:
        raise LookupFailed("%s: bad JSON: %s" % (url, e))


# ---- parsers (pure, unit tested) -------------------------------------------

def strip_v(tag):
    return re.sub(r"^(rust-)?v", "", tag)


def parse_go(data):
    for rel in data:
        if not rel.get("stable"):
            continue
        out = {"GO_VERSION": rel["version"][2:]}
        for up, arch in ARCHES.items():
            match = [f for f in rel["files"] if f["os"] == "linux" and f["arch"] == arch and f["kind"] == "archive"]
            if not match:
                raise LookupFailed("go: no linux/%s archive" % arch)
            out["GO_SHA256_" + up] = match[0]["sha256"]
        return out
    raise LookupFailed("go: no stable release")


def parse_rust_channel(text):
    m = re.search(r'\[pkg\.rustc\]\s*\nversion = "([0-9.]+) ', text)
    if not m:
        raise LookupFailed("rust: no pkg.rustc version")
    return m.group(1)


def parse_rustup_release(text):
    m = re.search(r"^version = '([0-9.]+)'", text, re.M)
    if not m:
        raise LookupFailed("rustup: no version")
    return m.group(1)


def asset_sha256(release, name, fetch_text=None):
    """Require published SHA-256 files to agree with GitHub's asset digest.

    Projects use GNU checksum lists, BSD SHA256 lists, or per-asset .sha256 files.
    GitHub's server-computed digest is a fallback only when no such file exists.
    """
    tag = release.get("tag_name")
    assets = release.get("assets", [])
    match = [asset for asset in assets if asset["name"] == name]
    if len(match) != 1:
        raise LookupFailed("%s: asset %s missing or ambiguous" % (tag, name))
    digest = match[0].get("digest") or ""
    value = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
    if digest and (not digest.startswith("sha256:") or not HEX64.fullmatch(value)):
        raise LookupFailed("%s: malformed asset digest" % tag)
    files = [asset for asset in assets if asset["name"] == name + ".sha256"]
    if not files:
        files = [asset for asset in assets if asset["name"].endswith(("checksums.txt", "SHA256SUMS"))
                 or asset["name"] in ("sha256.sum", "checksums-bsd")]
    published = set()
    for asset in files:
        text = (fetch_text or fetch)(asset["browser_download_url"])
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == name and HEX64.fullmatch(parts[0]):
                published.add(parts[0])
            bsd = re.fullmatch(r"SHA256\s+\(" + re.escape(name) + r"\) = ([0-9a-f]{64})", line)
            if bsd:
                published.add(bsd.group(1))
    if files:
        if len(published) != 1 or (digest and value not in published):
            raise LookupFailed("%s: missing or conflicting published sha256 for %s" % (tag, name))
        return published.pop()
    if digest:
        return value
    raise LookupFailed("%s: no sha256 for asset %s" % (tag, name))


def parse_checksum_file(text):
    parts = text.split()
    if not parts or not HEX64.match(parts[0]):
        raise LookupFailed("checksum file does not start with a sha256: %r" % text[:60])
    return parts[0]


def parse_agy(manifest):
    try:
        version, url, sha = (manifest[k] for k in AGY_KEYS)
    except KeyError as e:
        raise LookupFailed("agy manifest: missing %s" % e)
    problem = agy_url_problem(url)
    if problem:
        raise LookupFailed("agy manifest: %s" % problem)
    if not HEX128.match(sha):
        raise LookupFailed("agy manifest: malformed sha512")
    return version, url, sha


# ---- resolvers (network) ---------------------------------------------------

def gh_latest(repo):
    return fetch_json("https://api.github.com/repos/%s/releases/latest" % repo)


def r_base():
    tag = fetch_json("https://hub.docker.com/v2/repositories/library/ubuntu/tags/26.04")
    snap = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).strftime("%Y%m%dT000000Z")
    return {"BASE_IMAGE": "docker.io/library/ubuntu:26.04@" + tag["digest"], "APT_SNAPSHOT": snap}


def r_go():
    return parse_go(fetch_json("https://go.dev/dl/?mode=json"))


def rust_manifest_url(version):
    return "https://static.rust-lang.org/dist/channel-rust-%s.toml" % version


def r_rust():
    rustup = parse_rustup_release(fetch("https://static.rust-lang.org/rustup/release-stable.toml"))
    rust = parse_rust_channel(fetch("https://static.rust-lang.org/dist/channel-rust-stable.toml"))
    out = {"RUSTUP_VERSION": rustup, "RUST_VERSION": rust,
           # rustup checks every component against this versioned manifest; the build checks the manifest.
           "RUST_MANIFEST_SHA256": parse_checksum_file(fetch(rust_manifest_url(rust) + ".sha256"))}
    for up, triple in (("AMD64", "x86_64-unknown-linux-gnu"), ("ARM64", "aarch64-unknown-linux-gnu")):
        url = "https://static.rust-lang.org/rustup/archive/%s/%s/rustup-init.sha256" % (rustup, triple)
        out["RUSTUP_SHA256_" + up] = parse_checksum_file(fetch(url))
    return out


def github_tool(prefix, repo, names):
    """names maps AMD64/ARM64 to a function of the bare version returning the asset name."""
    rel = gh_latest(repo)
    ver = strip_v(rel["tag_name"])
    out = {prefix + "_VERSION": ver}
    for up, fn in names.items():
        name = fn(ver)
        checksum = asset_sha256(rel, name)
        try:
            supported = verify_asset(repo, rel, name, checksum, fetch_bytes)
        except VerificationFailed as error:
            raise LookupFailed(str(error)) from error
        if not supported:
            print("%s: publisher signature verification not verified; retaining checksum checks" % repo,
                  file=sys.stderr)
        out["%s_SHA256_%s" % (prefix, up)] = checksum
    return out


def r_yq():
    return github_tool("YQ", "mikefarah/yq", {"AMD64": lambda v: "yq_linux_amd64", "ARM64": lambda v: "yq_linux_arm64"})


def r_gh():
    return github_tool("GH", "cli/cli", {
        "AMD64": lambda v: "gh_%s_linux_amd64.tar.gz" % v, "ARM64": lambda v: "gh_%s_linux_arm64.tar.gz" % v})


def r_uv():
    return github_tool("UV", "astral-sh/uv", {
        "AMD64": lambda v: "uv-x86_64-unknown-linux-gnu.tar.gz", "ARM64": lambda v: "uv-aarch64-unknown-linux-gnu.tar.gz"})


def r_ruff():
    # Official release binaries and per-asset checksums: https://github.com/astral-sh/ruff/releases
    return github_tool("RUFF", "astral-sh/ruff", {
        "AMD64": lambda v: "ruff-x86_64-unknown-linux-gnu.tar.gz",
        "ARM64": lambda v: "ruff-aarch64-unknown-linux-gnu.tar.gz"})


def r_trivy():
    out = github_tool("TRIVY", "aquasecurity/trivy", {
        "AMD64": lambda v: "trivy_%s_Linux-64bit.tar.gz" % v,
        "ARM64": lambda v: "trivy_%s_Linux-ARM64.tar.gz" % v})
    tag = out["TRIVY_VERSION"]
    out["TRIVY_SCANNER_IMAGE"] = hub_ref("aquasec/trivy", tag, fetch_json(
        "https://hub.docker.com/v2/repositories/aquasec/trivy/tags/" + tag))
    return out


def r_abtop():
    # Official release binaries and per-asset checksums: https://github.com/graykode/abtop/releases
    return github_tool("ABTOP", "graykode/abtop", {
        "AMD64": lambda v: "abtop-x86_64-unknown-linux-gnu.tar.xz",
        "ARM64": lambda v: "abtop-aarch64-unknown-linux-gnu.tar.xz"})


def r_unslop():
    # The pstack directory includes the skill and its license. Source files have no
    # published checksums, so compute both from the same immutable upstream commit.
    # https://github.com/cursor/plugins/tree/main/pstack
    commits = fetch_json('https://api.github.com/repos/cursor/plugins/commits?path=pstack&per_page=1')
    if not commits or not isinstance(commits[0], dict):
        raise LookupFailed('unslop: no upstream commit')
    commit = commits[0].get('sha', '')
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise LookupFailed('unslop: expected a full lowercase commit SHA')
    base = 'https://raw.githubusercontent.com/cursor/plugins/' + commit + '/pstack/'
    return {'UNSLOP_COMMIT': commit,
            'UNSLOP_SHA256': hashlib.sha256(fetch_bytes(base + 'skills/unslop/SKILL.md')).hexdigest(),
            'UNSLOP_LICENSE_SHA256': hashlib.sha256(fetch_bytes(base + 'LICENSE')).hexdigest()}


def r_golangci():
    return github_tool("GOLANGCI_LINT", "golangci/golangci-lint", {
        "AMD64": lambda v: "golangci-lint-%s-linux-amd64.tar.gz" % v,
        "ARM64": lambda v: "golangci-lint-%s-linux-arm64.tar.gz" % v})


def r_kubectl():
    # https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/
    tag = fetch("https://dl.k8s.io/release/stable.txt").strip()
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise LookupFailed("kubectl: stable release must be a version tag")
    out = {"KUBECTL_VERSION": tag[1:]}
    for up, arch in ARCHES.items():
        out["KUBECTL_SHA256_" + up] = parse_checksum_file(fetch(
            "https://dl.k8s.io/release/%s/bin/linux/%s/kubectl.sha256" % (tag, arch)))
    return out


def r_helm():
    # https://helm.sh/docs/intro/install/#from-the-binary-releases
    release = gh_latest("helm/helm")
    tag = release["tag_name"]
    if release.get("prerelease") or release.get("draft") or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise LookupFailed("helm: latest release must be a stable version tag")
    out = {"HELM_VERSION": tag[1:]}
    for up, arch in ARCHES.items():
        name = "helm-%s-linux-%s.tar.gz" % (tag, arch)
        parts = fetch("https://get.helm.sh/" + name + ".sha256sum").split()
        if len(parts) != 2 or parts[1].lstrip("*") != name or not HEX64.fullmatch(parts[0]):
            raise LookupFailed("helm: invalid or mismatched checksum for " + name)
        out["HELM_SHA256_" + up] = parts[0]
    return out


def codex_asset(triple):
    # The complete package (bin/codex, codex-code-mode-host, rg, bwrap, codex-package.json).
    # The interactive CLI refuses to start from the bare binary ("this CLI has no complete
    # local package"); OpenAI's own installer uses this asset (chatgpt.com/codex/install.sh).
    return "codex-package-%s-unknown-linux-musl.tar.gz" % triple


def r_codex():
    return github_tool("CODEX", "openai/codex", {
        "AMD64": lambda v: codex_asset("x86_64"),
        "ARM64": lambda v: codex_asset("aarch64")})


def r_tea():
    rel = fetch_json("https://gitea.com/api/v1/repos/gitea/tea/releases/latest")
    ver = strip_v(rel["tag_name"])
    out = {"TEA_VERSION": ver}
    for up, arch in ARCHES.items():
        name = "tea-%s-linux-%s.xz.sha256" % (ver, arch)
        assets = [a for a in rel.get("assets", []) if a["name"] == name]
        if not assets:
            raise LookupFailed("tea: %s not found" % name)
        out["TEA_SHA256_" + up] = parse_checksum_file(fetch(assets[0]["browser_download_url"]))
    return out


# Claude Code's native release host, the one https://claude.ai/install.sh downloads from.
# Each release's manifest.json lists a SHA-256 per platform and is signed with this key
# (code.claude.com/docs/en/setup, "Binary integrity and code signing").
CLAUDE_RELEASES = "https://downloads.claude.ai/claude-code-releases"
CLAUDE_KEY_URL = "https://downloads.claude.ai/keys/claude-code.asc"
CLAUDE_KEY_FINGERPRINT = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"
CLAUDE_PLATFORMS = (("AMD64", "linux-x64"), ("ARM64", "linux-arm64"))
# Node's active release keys, listed after the README marker <!-- Active releasers keys --> in nodejs/release-keys at
# commit 481637f813e912c4aa3622d7964ab426c97b8e8d. NODE_KEYRING holds exactly these keys.
NODE_KEY_FINGERPRINTS = (
    "5BE8A3F6C8A5C01D106C0AD820B1A390B168D356",
    "DD792F5973C6DE52C432CBDAC77ABFA00DDBF2B7",
    "CC68F5A3106FF448322E48ED27F5E38D5B0A215F",
    "890C08DB8579162FEE0DF9DB8BEAB4DFCF555EF4",
    "C82FA3AE1CBEDC6BE46B9360C43CEC45C17AB93C",
    "108F52B48DB57BB0CC439B2997B01419BD92F80A",
    "655F3B5C1FB3FA8D1A0CA6BDE4A7D232B936D2FD",
    "A363A499291CBBC940DD62E41F10027AF002F8B0",
)
NODE_KEYRING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys", "nodejs-release-keys.asc")


def parse_claude_manifest(doc, ver):
    """The pins for one Claude Code release from its manifest.json."""
    if doc.get("version") != ver:
        raise LookupFailed("claude: manifest is for %r, not %s" % (doc.get("version"), ver))
    out = {"CLAUDE_CODE_VERSION": ver}
    for up, platform in CLAUDE_PLATFORMS:
        checksum = ((doc.get("platforms") or {}).get(platform) or {}).get("checksum", "")
        if not HEX64.match(checksum):
            raise LookupFailed("claude %s: no valid checksum for %s" % (ver, platform))
        out["CLAUDE_CODE_SHA256_" + up] = checksum
    return out


def verify_signature(data, sig, key, fingerprints):
    """Raise LookupFailed unless sig is a valid signature of data by a key in the set fingerprints.

    fingerprints is one fingerprint or a tuple of them. The key file must hold exactly that set
    of primary keys, and gpg's status output must name one of them as the signer. gpg --verify
    alone accepts a signature by any key in the keyring.
    """
    wanted = frozenset([fingerprints] if isinstance(fingerprints, str) else fingerprints)
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, GNUPGHOME=home)
        paths = {}
        for name, content in (("key", key), ("data", data), ("sig", sig)):
            paths[name] = os.path.join(home, name)
            with open(paths[name], "wb") as f:
                f.write(content)
        gpg = ["gpg", "--batch", "--no-tty"]
        try:
            subprocess.run(gpg + ["--import", paths["key"]], env=env, check=True, capture_output=True)
            listing = subprocess.run(gpg + ["--with-colons", "--fingerprint"], env=env, check=True,
                                     capture_output=True, text=True).stdout
            lines = listing.splitlines()
            # The fpr line right after each pub line is that primary key's fingerprint.
            primaries = [lines[i + 1].split(":")[9] for i, line in enumerate(lines)
                         if line.startswith("pub:") and i + 1 < len(lines) and lines[i + 1].startswith("fpr:")]
            if len(primaries) != len(wanted) or set(primaries) != wanted:
                raise LookupFailed("signing key file holds %s, expected only %s"
                                   % (sorted(primaries), sorted(wanted)))
            # --trusted-key accepts these keys for the check without a trust database entry.
            trusted = [arg for fpr in sorted(wanted) for arg in ("--trusted-key", fpr[-16:])]
            status = subprocess.run(gpg + ["--status-fd", "1"] + trusted + ["--verify", paths["sig"], paths["data"]],
                                    env=env, check=True, capture_output=True, text=True).stdout
        except (OSError, subprocess.CalledProcessError) as e:
            raise LookupFailed("signature check failed: %s" % e)
    # GnuPG doc/DETAILS: GOODSIG means a good signature by a key that is neither expired nor
    # revoked; the last VALIDSIG field is the signing key's primary key fingerprint.
    words = [line.split() for line in status.splitlines() if line.startswith("[GNUPG:] ")]
    good = any(w[1] == "GOODSIG" for w in words if len(w) > 1)
    signers = [w[-1] for w in words if len(w) > 2 and w[1] == "VALIDSIG"]
    if not good or len(signers) != 1 or signers[0] not in wanted:
        bad = sorted({w[1] for w in words if len(w) > 1 and w[1] in ("EXPKEYSIG", "REVKEYSIG")})
        if bad:
            raise LookupFailed("signature check reported %s; the pinned signing key needs a hand update"
                               % " and ".join(bad))
        raise LookupFailed("signature is not a good signature by one of %s" % sorted(wanted))


def r_claude():
    # The "stable" channel Anthropic documents for Claude Code (code.claude.com/docs/en/setup).
    ver = fetch(CLAUDE_RELEASES + "/stable").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", ver):
        raise LookupFailed("claude: unexpected stable version %r" % ver[:40])
    base = "%s/%s/" % (CLAUDE_RELEASES, ver)
    manifest = fetch_bytes(base + "manifest.json")
    verify_signature(manifest, fetch_bytes(base + "manifest.json.sig"), fetch_bytes(CLAUDE_KEY_URL),
                     CLAUDE_KEY_FINGERPRINT)
    return parse_claude_manifest(json.loads(manifest), ver)


NODE_DIST = "https://nodejs.org/dist"
NODE_MAJOR = 26


def parse_node_index(doc, major):
    """Newest release of one Node.js major from nodejs.org/dist/index.json, without the v."""
    if not isinstance(doc, list):
        raise LookupFailed("node: unexpected index.json shape")
    pattern = re.compile(r"v(%d\.[0-9]+\.[0-9]+)" % major)
    found = [m.group(1) for m in (pattern.fullmatch(str(e.get("version", ""))) for e in doc if isinstance(e, dict))
             if m]
    if not found:
        raise LookupFailed("node: no release of major %d in index.json" % major)
    return max(found, key=version_key)


def parse_node_shasums(text, ver):
    """Both linux tarball hashes for one version from SHASUMS256.txt."""
    names = {"NODE_SHA256_AMD64": "node-v%s-linux-x64.tar.xz" % ver,
             "NODE_SHA256_ARM64": "node-v%s-linux-arm64.tar.xz" % ver}
    hashes = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            hashes[parts[1]] = parts[0]
    out = {"NODE_VERSION": ver}
    for key, name in names.items():
        digest = hashes.get(name, "")
        if not HEX64.match(digest):
            raise LookupFailed("node: no valid sha256 for %s in SHASUMS256.txt" % name)
        out[key] = digest
    return out


def r_node():
    # nodejs.org signs SHASUMS256.txt with the release keys pinned in scripts/keys.
    ver = parse_node_index(fetch_json(NODE_DIST + "/index.json"), NODE_MAJOR)
    base = "%s/v%s/SHASUMS256.txt" % (NODE_DIST, ver)
    shasums = fetch_bytes(base)
    sig = fetch_bytes(base + ".sig")
    with open(NODE_KEYRING, "rb") as f:
        key = f.read()
    verify_signature(shasums, sig, key, NODE_KEY_FINGERPRINTS)
    return parse_node_shasums(shasums.decode(), ver)


def r_agy():
    out = {}
    versions = set()
    for up, arch in ARCHES.items():
        ver, url, sha = parse_agy(fetch_json(AGY_MANIFEST.format(arch=arch)))
        versions.add(ver)
        out["AGY_URL_" + up] = url
        out["AGY_SHA512_" + up] = sha
    if len(versions) != 1:
        raise LookupFailed("agy: architectures disagree on version %s" % sorted(versions))
    out["AGY_VERSION"] = versions.pop()
    return out


def r_opencode():
    ver = fetch_json("https://registry.npmjs.org/@opencode/cli/latest")["version"]
    out = {"OPENCODE_VERSION": ver}
    for up, target in (("AMD64", "linux-x64-baseline"), ("ARM64", "linux-arm64")):
        meta = fetch_json("https://registry.npmjs.org/@opencode/cli-%s/%s" % (target, ver))
        out["OPENCODE_INTEGRITY_" + up] = meta["dist"]["integrity"]
    return out


# ---- extras ----------------------------------------------------------------

NPM_REGISTRY = "https://registry.npmjs.org/"
EXTRAS_DIR = "rootfs/usr/local/share/agentainer/extras"
# (versions.env key, npm package, catalog directory under EXTRAS_DIR)
EXTRAS = (("KANDEV_VERSION", "kandev", "kandev"),
          ("OPENCHAMBER_VERSION", "@openchamber/web", "openchamber"),
          ("REA_VERSION", "rea-agents", "rea"))
EXTRA_MIN_AGE_DAYS = 7
# Packages whose install scripts may appear in a lockfile. Extras install with
# npm ci --ignore-scripts, so no install script runs. node-pty 1.2.0-beta.15 ships
# prebuilds/linux-x64 and prebuilds/linux-arm64
# (https://unpkg.com/node-pty@1.2.0-beta.15/?meta), and its install script
# scripts/prebuild.js only checks that prebuilds/<platform>-<arch> exists
# (https://unpkg.com/node-pty@1.2.0-beta.15/scripts/prebuild.js). rea keeps
# optional dependencies, so frida installs without running its install script
# (npm ci --ignore-scripts).
INSTALL_SCRIPT_ALLOWLIST = frozenset(("node-pty", "frida"))
# Both keys from https://registry.npmjs.org/-/npm/v1/keys, copied verbatim on 2026-11-01.
NPM_KEYS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys", "npm-registry-keys.json")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STABLE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
NPM_NAME = re.compile(r"(?:@([A-Za-z0-9._~-]+)/)?([A-Za-z0-9._~-]+)")
NPM_VERSION = re.compile(r"[0-9A-Za-z.+-]+")
# An npm version as node-semver parses it: MAJOR.MINOR.PATCH, an optional -prerelease and an
# optional +build (https://docs.npmjs.com/about-semantic-versioning, https://semver.org/#spec-item-9).
NPM_SEMVER = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")
REGISTRY_TIME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.[0-9]+)?Z")


def npm_name_ok(name):
    """True when name follows npm's package name rules.

    https://docs.npmjs.com/cli/v11/configuring-npm/package-json#name: at most 214
    characters including the scope, URL-safe, and an unscoped name must not begin
    with a dot or an underscore (a scoped one may). "." and ".." are refused in
    either part because the name becomes part of a registry URL path.
    """
    m = NPM_NAME.fullmatch(name) if isinstance(name, str) else None
    if not m or len(name) > 214:
        return False
    scope, pkg = m.groups()
    if scope is None:
        return not pkg.startswith((".", "_"))
    return scope not in (".", "..") and pkg not in (".", "..")


class NothingNewer(LookupFailed):
    """The registry has no version that may replace the pin yet. Not a failed check."""


class ExtraFiles:
    """Catalog files r_extras computed in one run of main.

    main calls reset before the resolvers run and writes files only after every
    resolver and check passed. Paths in files are relative to base. failures holds
    one "extras <name>: <reason>" line per extra whose checks failed.
    """

    def __init__(self):
        self.reset(None, {})

    def reset(self, base, pins):
        self.base = base
        self.pins = dict(pins)
        self.files = {}
        self.regenerated = []
        self.failures = []


EXTRA_FILES = ExtraFiles()


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_registry_time(value):
    """A registry timestamp such as 2025-01-29T00:00:00.000Z as an aware UTC datetime."""
    m = REGISTRY_TIME.fullmatch(value) if isinstance(value, str) else None
    if not m:
        raise LookupFailed("unexpected registry time %r" % (value,))
    when = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    return when + datetime.timedelta(seconds=float("0" + (m.group(2) or "")))


def npm_version_key(value):
    """Sort key for an npm version: (major, minor, patch, 0 for a prerelease or 1 for a release).

    A prerelease sorts below the release with the same major, minor and patch, as in
    https://semver.org/#spec-item-11. Prerelease identifiers and build metadata are not compared,
    because the extras resolver only picks releases. Raises ValueError for any other string.
    """
    m = NPM_SEMVER.fullmatch(value) if isinstance(value, str) else None
    if not m:
        raise ValueError("invalid npm version %r" % (value,))
    return tuple(int(n) for n in m.group(1, 2, 3)) + (int(m.group(4) is None),)


def pick_version(packument, now):
    """Newest stable, non-deprecated version up to dist-tags.latest published at least EXTRA_MIN_AGE_DAYS before now."""
    if not isinstance(packument, dict) or not isinstance(packument.get("versions"), dict):
        raise LookupFailed("packument is not an object with versions")
    latest = npm_version_key(packument["dist-tags"]["latest"])
    times = packument.get("time")
    if not isinstance(times, dict) or not times:
        raise LookupFailed("packument has no time object")
    cutoff = now - datetime.timedelta(days=EXTRA_MIN_AGE_DAYS)
    found = []
    candidates = timed = 0
    for ver, meta in packument["versions"].items():
        if not STABLE_VERSION.fullmatch(ver) or (isinstance(meta, dict) and meta.get("deprecated")):
            continue
        if npm_version_key(ver) > latest:
            continue
        candidates += 1
        try:
            published = parse_registry_time(times.get(ver))
        except LookupFailed:
            continue
        timed += 1
        if published <= cutoff:
            found.append(ver)
    if candidates and not timed:
        raise LookupFailed("packument time has no valid entry for any stable version")
    if not found:
        raise NothingNewer("no stable version published at least %d days ago" % EXTRA_MIN_AGE_DAYS)
    return max(found, key=npm_version_key)


def lock_entry_name(path, entry):
    """Package name of a lockfile packages entry. Aliased packages record their real name in "name"."""
    return entry.get("name") or path.rsplit("node_modules/", 1)[-1]


def new_install_scripts(old_lock, new_lock):
    """Names of packages with hasInstallScript in new_lock and in no entry of old_lock, minus the allowlist."""
    def flagged(lock):
        return {lock_entry_name(path, entry) for path, entry in (lock.get("packages") or {}).items()
                if path and isinstance(entry, dict) and entry.get("hasInstallScript")}
    return sorted(flagged(new_lock) - flagged(old_lock) - INSTALL_SCRIPT_ALLOWLIST)


def load_registry_keys(path):
    """The keys of an npm /-/npm/v1/keys document, by keyid."""
    with open(path) as f:
        doc = json.load(f)
    keys = {}
    for key in doc["keys"]:
        if key.get("keytype") != "ecdsa-sha2-nistp256" or key.get("scheme") != "ecdsa-sha2-nistp256":
            raise LookupFailed("%s: unsupported key type for %s" % (path, key.get("keyid")))
        keys[key["keyid"]] = key
    return keys


def verify_registry_signature(name, version, integrity, signatures, keys, published=None):
    """Raise LookupFailed unless one of signatures verifies against a key in keys.

    The registry signs "<name>@<version>:<integrity>" with ECDSA P-256 over SHA-256
    (https://docs.npmjs.com/about-registry-signatures). sig is a base64 DER signature
    and key is a base64 DER SubjectPublicKeyInfo. A key with "expires" counts only
    for a version published before that time, as npm does (npm/pacote lib/registry.js).
    published is a function returning the version's publish time; it is called only
    for such a key.
    """
    message = ("%s@%s:%s" % (name, version, integrity)).encode()
    reasons = []
    with tempfile.TemporaryDirectory() as tmp:
        paths = {n: os.path.join(tmp, n) for n in ("data", "key", "sig")}
        with open(paths["data"], "wb") as f:
            f.write(message)
        for signature in signatures or []:
            keyid = signature.get("keyid") if isinstance(signature, dict) else None
            key = keys.get(keyid)
            if key is None:
                reasons.append("unknown keyid %r" % (keyid,))
                continue
            if key.get("expires"):
                try:
                    when = published() if published else None
                except LookupFailed as e:
                    reasons.append("no publish time for key %s: %s" % (keyid, e))
                    continue
                if when is None or not when < parse_registry_time(key["expires"]):
                    reasons.append("key %s expired %s, before this version was published" % (keyid, key["expires"]))
                    continue
            try:
                der_key = base64.b64decode(key["key"], validate=True)
                der_sig = base64.b64decode(signature["sig"], validate=True)
            except (KeyError, TypeError, binascii.Error):
                reasons.append("malformed signature or key for %s" % keyid)
                continue
            for n, content in (("key", der_key), ("sig", der_sig)):
                with open(paths[n], "wb") as f:
                    f.write(content)
            try:
                result = subprocess.run(["openssl", "dgst", "-sha256", "-verify", paths["key"], "-keyform", "DER",
                                         "-signature", paths["sig"], paths["data"]],
                                        capture_output=True, text=True)
            except OSError as e:
                raise LookupFailed("openssl: %s" % e)
            if result.returncode == 0 and "Verified OK" in result.stdout:
                return
            reasons.append("signature by %s does not verify" % keyid)
    raise LookupFailed("%s@%s: no registry signature verifies (%s)"
                       % (name, version, "; ".join(reasons) or "no signatures"))


def check_lockfile(lock, fetch_json=fetch_json, keys=None):
    """Raise LookupFailed unless every downloaded package in lock matches a signed registry entry.

    Each entry must come from the public registry with an integrity equal to the
    registry's dist.integrity for that version, and that integrity must carry a
    registry signature. Bundled entries ship inside their parent's tarball, so the
    parent's integrity covers them. A link entry points outside the registry and is refused.
    """
    keys = load_registry_keys(NPM_KEYS) if keys is None else keys
    packages = lock.get("packages") if isinstance(lock, dict) else None
    if not isinstance(packages, dict):
        raise LookupFailed("lockfile has no packages object")
    packuments = {}
    for path, entry in sorted(packages.items()):
        if not isinstance(entry, dict):
            raise LookupFailed("%s: lockfile entry is not an object" % path)
        if not path:
            continue
        if entry.get("link"):
            raise LookupFailed("%s: lockfile entry is a link" % path)
        if entry.get("inBundle"):
            continue
        name, version, integrity = lock_entry_name(path, entry), entry.get("version"), entry.get("integrity")
        if not npm_name_ok(name) or not isinstance(version, str) or not NPM_VERSION.fullmatch(version):
            raise LookupFailed("%s: unexpected name or version" % path)
        if not integrity or not isinstance(integrity, str):
            raise LookupFailed("%s: lockfile entry has no integrity" % path)
        if not str(entry.get("resolved", "")).startswith(NPM_REGISTRY):
            raise LookupFailed("%s: resolved outside %s" % (path, NPM_REGISTRY))
        doc = fetch_json(NPM_REGISTRY + name + "/" + version)
        dist = doc.get("dist") if isinstance(doc, dict) else None
        if not isinstance(dist, dict) or not isinstance(dist.get("signatures", []), list):
            raise LookupFailed("%s@%s: registry document has no dist object" % (name, version))
        if dist.get("integrity") != integrity:
            raise LookupFailed("%s@%s: registry integrity differs from the lockfile" % (name, version))

        # The per-version document has no publish time; the full packument's time map does.
        def published(name=name, version=version):
            if name not in packuments:
                packuments[name] = fetch_json(NPM_REGISTRY + name)
            doc = packuments[name]
            times = doc.get("time") if isinstance(doc, dict) else None
            return parse_registry_time(times.get(version) if isinstance(times, dict) else None)

        verify_registry_signature(name, version, integrity, dist.get("signatures") or [], keys, published=published)


def npm_lockfile(package_json, now):
    """package-lock.json text that npm generates for package_json, without running package code.

    --before applies the same release-age rule to every dependency in the tree
    (https://docs.npmjs.com/cli/v11/using-npm/config#before). The empty userconfig
    keeps a local ~/.npmrc from changing the registry or other settings.
    """
    before = (now - datetime.timedelta(days=EXTRA_MIN_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        os.mkdir(work)
        with open(os.path.join(work, "package.json"), "w") as f:
            f.write(package_json)
        userconfig = os.path.join(tmp, "npmrc")
        open(userconfig, "w").close()
        argv = ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund",
                "--cache=" + os.path.join(tmp, "cache"), "--userconfig=" + userconfig,
                "--registry=" + NPM_REGISTRY, "--before=" + before]
        try:
            subprocess.run(argv, cwd=work, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            tail = " ".join((e.stderr or "").strip().splitlines()[-3:])
            raise LookupFailed("npm install exited %d: %s" % (e.returncode, tail))
        except OSError as e:
            raise LookupFailed("npm: %s" % e)
        with open(os.path.join(work, "package-lock.json")) as f:
            return f.read()


def extra_update(base, pin, name, extra, now):
    """(version, {relative path: text}) for one extra, or None when its pin stays."""
    rel = EXTRAS_DIR + "/" + extra
    directory = os.path.join(base, rel)
    if pin is None or not os.path.isdir(directory):
        what = "no pin in versions.env" if pin is None else "no catalog directory %s" % rel
        print("bump_versions: extras %s: %s; skipped" % (extra, what), file=sys.stderr)
        return None
    ver = pick_version(fetch_json(NPM_REGISTRY + name), now)
    if npm_version_key(ver) <= npm_version_key(pin):
        if npm_version_key(ver) < npm_version_key(pin):
            print("bump_versions: extras %s: registry offers %s, older than %s; pin unchanged" % (extra, ver, pin),
                  file=sys.stderr)
        return None
    with open(os.path.join(directory, "package.json")) as f:
        wrapper = json.load(f)
    if not isinstance(wrapper, dict) or not isinstance(wrapper.get("dependencies"), dict) \
            or list(wrapper["dependencies"]) != [name]:
        raise LookupFailed("%s/package.json must depend on exactly %s" % (rel, name))
    wrapper["dependencies"] = {name: ver}
    package_json = json.dumps(wrapper, indent=2) + "\n"
    with open(os.path.join(directory, "package-lock.json")) as f:
        old_lock = json.load(f)
    lock_text = npm_lockfile(package_json, now)
    new_lock = json.loads(lock_text)
    for label, lock in (("committed", old_lock), ("generated", new_lock)):
        if not isinstance(lock, dict) or not isinstance(lock.get("packages"), dict):
            raise LookupFailed("%s lockfile has no packages object" % label)
    if (new_lock["packages"].get("node_modules/" + name) or {}).get("version") != ver:
        raise LookupFailed("generated lockfile does not hold %s@%s" % (name, ver))
    added = new_install_scripts(old_lock, new_lock)
    if added:
        raise LookupFailed("new install scripts in %s" % ", ".join(added))
    check_lockfile(new_lock)
    return ver, {rel + "/package.json": package_json, rel + "/package-lock.json": lock_text}


def r_extras():
    """Pins for the extras whose newer version passed every check.

    Their files go to EXTRA_FILES.files. A failed check for one extra, including
    malformed upstream data or a missing npm or openssl, keeps that extra's pin
    and goes to EXTRA_FILES.failures; the other extras continue.
    """
    base = EXTRA_FILES.base or REPO_ROOT
    now = utcnow()
    out = {}
    for key, name, extra in EXTRAS:
        try:
            result = extra_update(base, EXTRA_FILES.pins.get(key), name, extra, now)
        except NothingNewer as e:
            print("bump_versions: extras %s: %s; pin unchanged" % (extra, e), file=sys.stderr)
            continue
        except (LookupFailed, OSError, AttributeError, KeyError, IndexError, TypeError, ValueError) as e:
            print("bump_versions: extras %s: %s; pin unchanged" % (extra, e), file=sys.stderr)
            # One line per failure, so the --failures file has one entry per line.
            EXTRA_FILES.failures.append("extras %s: %s" % (extra, " ".join(str(e).split())))
            continue
        if result:
            out[key], files = result
            EXTRA_FILES.files.update(files)
            EXTRA_FILES.regenerated.append(extra)
    return out


K8S_IMAGES = (("CONTAINERSSH_IMAGE", "containerssh/containerssh", "v0.6",
                "deploy/kubernetes/containerssh/deployment.yaml"),
               ("WEBHOOK_PYTHON_IMAGE", "library/python", "3.14-slim",
                "deploy/kubernetes/auth-webhook/deployment.yaml"))


def hub_ref(repo, tag, data):
    digest = data.get("digest") or ""
    if not re.match(r"^sha256:[0-9a-f]{64}$", digest):
        raise LookupFailed("docker hub %s:%s: malformed digest %r" % (repo, tag, digest))
    return "docker.io/%s:%s@%s" % (repo, tag, digest)


def rewrite_image_ref(text, ref):
    """Replace any digest-pinned reference to the same image with ref."""
    image = ref.split("@")[0].rsplit(":", 1)[0]
    return re.sub(re.escape(image) + r":[^\s@]+@sha256:[0-9a-f]{64}", ref, text)


def r_k8s_images():
    return {key: hub_ref(repo, tag, fetch_json("https://hub.docker.com/v2/repositories/%s/tags/%s" % (repo, tag)))
            for key, repo, tag, _ in K8S_IMAGES}


def buildkit_tag(releases):
    """Newest stable BuildKit release. The repo also tags Dockerfile frontend releases."""
    for r in releases:
        if not r.get("prerelease") and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", r.get("tag_name", "")):
            return r["tag_name"]
    raise LookupFailed("moby/buildkit: no stable release found")


def r_buildkit():
    # The BuildKit image buildx uses to build the published image (build.yml, publish job).
    tag = buildkit_tag(fetch_json("https://api.github.com/repos/moby/buildkit/releases?per_page=20"))
    return {"BUILDKIT_IMAGE": hub_ref("moby/buildkit", tag,
                                      fetch_json("https://hub.docker.com/v2/repositories/moby/buildkit/tags/%s" % tag))}


RESOLVERS = [r_base, r_go, r_rust, r_yq, r_gh, r_uv, r_ruff, r_trivy, r_abtop, r_unslop, r_golangci,
             r_kubectl, r_helm, r_tea, r_claude, r_node, r_codex, r_agy, r_opencode, r_k8s_images, r_buildkit,
             r_extras]


def write_atomic(path, text):
    """Replace path with text through a unique temp file in the same directory.

    The new file keeps the old file's permission bits; a new file gets 0666 minus the umask.
    """
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix="." + os.path.basename(path) + ".")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def main(argv=None, resolvers=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", default="versions.env")
    ap.add_argument("--only", nargs="*", help="resolver names such as r_go r_agy")
    ap.add_argument("--failures", help="file to list failed extras checks in, one per line (empty when none)")
    args = ap.parse_args(argv)
    EXTRA_FILES.reset(None, {})
    if args.failures:
        # A later workflow step reads this file, so it exists even when the run fails.
        try:
            write_atomic(args.failures, "")
        except OSError as e:
            print("bump_versions: cannot write --failures %s: %s" % (args.failures, e), file=sys.stderr)
            return 2
    try:
        rc = bump(args, resolvers)
    except BaseException:
        # report_failures never raises, so the original exception propagates unchanged.
        report_failures(args.failures)
        raise
    if not report_failures(args.failures) and rc == 0:
        # Failures that never reached the file would let the workflow job pass.
        return 2
    return rc


def report_failures(path):
    """Write the failed extras checks to path and print them, on every exit from main.

    Failed checks keep their pins while the other pins still go out. The lines
    go to path, which a later workflow step fails on when it is not empty, then
    to stdout (and a GitHub Actions warning). Never raises. Returns False when
    failures exist but path could not be written, True otherwise.
    """
    failures = list(EXTRA_FILES.failures)
    ok = True
    if path:
        try:
            write_atomic(path, "".join(line + "\n" for line in failures))
        except OSError as e:
            # main truncated path at the start, so it is empty rather than stale.
            ok = not failures
            try:
                print("bump_versions: cannot write --failures %s: %s" % (path, e), file=sys.stderr)
            except OSError:
                pass
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    try:
        for line in failures:
            if annotate:
                # Workflow command data escapes % as %25 (actions/toolkit packages/core/src/command.ts, escapeData).
                print("::warning::bump_versions: %s" % line.replace("%", "%25"))
            print(line)
    except OSError:
        # A closed stdout (BrokenPipeError) must not hide the exit code or exception from bump.
        pass
    return ok


def bump(args, resolvers):
    known = {r.__name__ for r in RESOLVERS}
    unknown = sorted(set(args.only or []) - known)
    if unknown:
        print("bump_versions: unknown resolver(s) %s; known: %s" % (", ".join(unknown), ", ".join(sorted(known))),
              file=sys.stderr)
        return 2
    chosen = resolvers or [r for r in RESOLVERS if not args.only or r.__name__ in args.only]
    with open(args.file) as f:
        lines = parse_env(f.read())
    # Every path main reads or writes besides args.file is relative to the directory that holds it.
    base = os.path.dirname(os.path.abspath(args.file))
    EXTRA_FILES.reset(base, values(lines))
    updates = {}
    try:
        for r in chosen:
            updates.update(r())
    except LookupFailed as e:
        print("bump_versions: %s" % e, file=sys.stderr)
        return 1
    except (KeyError, IndexError, TypeError, ValueError) as e:
        # Upstream returned something with an unexpected shape.
        print("bump_versions: unexpected upstream data in %s: %r" % (getattr(r, "__name__", r), e), file=sys.stderr)
        return 1
    bad = [why for why in (invalid(k, v) for k, v in sorted(updates.items())) if why]
    if bad:
        for why in bad:
            print("bump_versions: refusing to write %s" % why, file=sys.stderr)
        return 1
    old = values(lines)
    npm_keys = {key for key, _, _ in EXTRAS}
    for key, value in updates.items():
        if key.endswith("_VERSION") and key in old and old[key] != value:
            order = npm_version_key if key in npm_keys else version_key
            try:
                if order(strip_v(value)) < order(strip_v(old[key])):
                    raise ValueError("resolver would downgrade %s" % key)
            except ValueError as error:
                print("bump_versions: %s; pins unchanged" % error, file=sys.stderr)
                return 1
    for k in sorted(updates):
        if old.get(k) != updates[k]:
            print("%s: %s -> %s" % (k, old.get(k, "(new)"), updates[k]))
    for extra in EXTRA_FILES.regenerated:
        print("extras %s: lockfile regenerated" % extra)
    # versions.env goes last, so an interrupted run never pins a version whose catalog files are missing.
    for rel, text in sorted(EXTRA_FILES.files.items()):
        write_atomic(os.path.join(base, rel), text)
    # The Kubernetes example must use the same image references as versions.env.
    for key, _, _, rel in K8S_IMAGES:
        path = os.path.join(base, rel)
        if key in updates and os.path.exists(path):
            with open(path) as f:
                text = f.read()
            write_atomic(path, rewrite_image_ref(text, updates[key]))
    write_atomic(args.file, render_env(lines, updates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
