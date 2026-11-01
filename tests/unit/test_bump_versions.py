import base64
import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import bump_versions as bv  # noqa: E402


class EnvFileTests(unittest.TestCase):
    def test_failed_publisher_verification_preserves_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "versions.env")
            original = "UV_VERSION=0.13.0\n"
            with open(path, "w") as file:
                file.write(original)
            release = {"tag_name": "0.13.1", "assets": [
                {"name": "uv-test.tar.gz", "digest": "sha256:" + "a" * 64}]}
            with patch.object(bv, "gh_latest", return_value=release), \
                    patch.object(bv, "verify_asset", side_effect=bv.VerificationFailed("wrong signer")):
                resolver = lambda: bv.github_tool("UV", "astral-sh/uv", {"AMD64": lambda v: "uv-test.tar.gz"})
                self.assertNotEqual(bv.main(["--file", path], resolvers=[resolver]), 0)
            with open(path) as file:
                self.assertEqual(file.read(), original)

    def test_resolver_downgrade_preserves_the_pin_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "versions.env")
            original = "HELM_VERSION=4.3.1\n"
            with open(path, "w") as file:
                file.write(original)
            rc = bv.main(["--file", path], resolvers=[lambda: {"HELM_VERSION": "3.22.1"}])
            self.assertNotEqual(rc, 0)
            with open(path) as file:
                self.assertEqual(file.read(), original)

    def test_round_trip_keeps_comments_and_order(self):
        text = "# header\nA=1\n\n# note\nB=2\n"
        lines = bv.parse_env(text)
        out = bv.render_env(lines, {"B": "3", "C": "4"})
        self.assertEqual(out, "# header\nA=1\n\n# note\nB=3\nC=4\n")

    def test_values_reads_keys(self):
        self.assertEqual(bv.values(bv.parse_env("A=1\n#x\nB=two\n")), {"A": "1", "B": "two"})


class ParserTests(unittest.TestCase):
    def test_abtop_resolver_checks_both_published_archive_checksums(self):
        names = ["abtop-x86_64-unknown-linux-gnu.tar.xz", "abtop-aarch64-unknown-linux-gnu.tar.xz"]
        assets = []
        responses = {}
        for name, letter in zip(names, "ab"):
            assets.extend([{"name": name, "digest": "sha256:" + letter * 64},
                           {"name": name + ".sha256", "browser_download_url": "https://example.com/" + name}])
            responses["https://example.com/" + name] = letter * 64 + " *" + name + "\n"
        release = {"tag_name": "v0.5.5", "assets": assets}
        with patch.object(bv, "gh_latest", return_value=release) as latest, \
                patch.object(bv, "fetch", side_effect=responses.__getitem__) as fetched, \
                patch.object(bv, "verify_asset", return_value=False):
            pins = bv.r_abtop()
        latest.assert_called_once_with("graykode/abtop")
        self.assertEqual(fetched.call_count, 2)
        self.assertEqual(pins, {"ABTOP_VERSION": "0.5.5", "ABTOP_SHA256_AMD64": "a" * 64,
                                "ABTOP_SHA256_ARM64": "b" * 64})
        self.assertIn(bv.r_abtop, bv.RESOLVERS)

    def test_ruff_resolver_selects_both_official_archives_and_verifies_publisher(self):
        names = ["ruff-x86_64-unknown-linux-gnu.tar.gz", "ruff-aarch64-unknown-linux-gnu.tar.gz"]
        release = {"tag_name": "0.17.1", "assets": [
            {"name": name, "digest": "sha256:" + letter * 64}
            for name, letter in zip(names, "ab")]}
        with patch.object(bv, "gh_latest", return_value=release), \
                patch.object(bv, "verify_asset", return_value=True) as verify:
            pins = bv.r_ruff()
        self.assertEqual(pins, {"RUFF_VERSION": "0.17.1", "RUFF_SHA256_AMD64": "a" * 64,
                                "RUFF_SHA256_ARM64": "b" * 64})
        self.assertEqual([call.args[2] for call in verify.call_args_list], names)

    def test_bsd_and_per_asset_published_checksums(self):
        checksum = "a" * 64
        for filename, contents in (("checksums-bsd", "SHA256 (tool.tar.gz) = " + checksum),
                                   ("tool.tar.gz.sha256", checksum + "  tool.tar.gz"),
                                   ("codex-package_SHA256SUMS", checksum + "  tool.tar.gz")):
            release = {"tag_name": "v1", "assets": [
                {"name": "tool.tar.gz", "digest": "sha256:" + checksum},
                {"name": filename, "browser_download_url": "https://example.com/sums"}]}
            self.assertEqual(bv.asset_sha256(release, "tool.tar.gz", fetch_text=lambda url: contents), checksum)

    def test_published_checksum_must_agree_with_asset_digest(self):
        release = {"tag_name": "v1", "assets": [
            {"name": "tool.tar.gz", "digest": "sha256:" + "a" * 64},
            {"name": "checksums.txt", "browser_download_url": "https://example.com/checksums.txt"}]}
        with self.assertRaises(bv.LookupFailed):
            bv.asset_sha256(release, "tool.tar.gz", fetch_text=lambda url: "b" * 64 + "  tool.tar.gz\n")

    def test_buildkit_skips_frontend_tags_and_prereleases(self):
        releases = [
            {"tag_name": "dockerfile/1.28.0", "prerelease": False},
            {"tag_name": "v0.35.0-rc1", "prerelease": True},
            {"tag_name": "v0.34.0", "prerelease": False},
            {"tag_name": "v0.33.1", "prerelease": False},
        ]
        self.assertEqual(bv.buildkit_tag(releases), "v0.34.0")

    def test_buildkit_without_a_release_fails(self):
        with self.assertRaises(bv.LookupFailed):
            bv.buildkit_tag([{"tag_name": "dockerfile/1.28.0", "prerelease": False}])

    def test_go_picks_first_stable_linux_archives(self):
        data = [
            {"version": "go1.28rc1", "stable": False, "files": []},
            {"version": "go1.27.2", "stable": True, "files": [
                {"os": "linux", "arch": "amd64", "kind": "archive", "sha256": "aa"},
                {"os": "linux", "arch": "arm64", "kind": "archive", "sha256": "bb"},
                {"os": "darwin", "arch": "arm64", "kind": "archive", "sha256": "cc"},
            ]},
        ]
        self.assertEqual(bv.parse_go(data), {
            "GO_VERSION": "1.27.2", "GO_SHA256_AMD64": "aa", "GO_SHA256_ARM64": "bb"})

    def test_rust_version_from_channel(self):
        text = '[pkg.rustc]\nversion = "1.99.0 (b940084d7 2026-09-28)"\n'
        self.assertEqual(bv.parse_rust_channel(text), "1.99.0")

    def test_rust_manifest_url(self):
        self.assertEqual(bv.rust_manifest_url("1.99.0"),
                         "https://static.rust-lang.org/dist/channel-rust-1.99.0.toml")

    def test_rustup_version(self):
        self.assertEqual(bv.parse_rustup_release("schema-version = '1'\nversion = '1.28.2'\n"), "1.28.2")

    def test_github_asset_digest(self):
        release = {"tag_name": "v4.54.1", "assets": [
            {"name": "yq_linux_amd64", "digest": "sha256:" + "1" * 64},
            {"name": "yq_linux_arm64", "digest": "sha256:" + "2" * 64}]}
        self.assertEqual(bv.asset_sha256(release, "yq_linux_arm64"), "2" * 64)

    def test_github_asset_without_digest_uses_release_checksums_file(self):
        release = {"tag_name": "v1.0.0", "assets": [
            {"name": "tool_1.0.0_linux_arm64.tar.gz", "digest": None},
            {"name": "tool_1.0.0_checksums.txt", "digest": None,
             "browser_download_url": "https://example.com/tool_1.0.0_checksums.txt"}]}
        a, b = "a" * 64, "b" * 64
        text = "%s  tool_1.0.0_linux_amd64.tar.gz\n%s  tool_1.0.0_linux_arm64.tar.gz\n" % (a, b)
        got = bv.asset_sha256(release, "tool_1.0.0_linux_arm64.tar.gz", fetch_text=lambda url: text)
        self.assertEqual(got, b)

    def test_github_asset_without_any_checksum_raises(self):
        release = {"tag_name": "v1", "assets": [{"name": "x.tar.gz", "digest": None}]}
        with self.assertRaises(bv.LookupFailed):
            bv.asset_sha256(release, "x.tar.gz", fetch_text=lambda url: "")

    def test_github_asset_missing_raises(self):
        with self.assertRaises(bv.LookupFailed):
            bv.asset_sha256({"tag_name": "v1", "assets": []}, "nope")

    def test_checksum_file_line(self):
        h = "0123456789abcdef" * 4
        self.assertEqual(bv.parse_checksum_file(h + "  tea-0.16.0-linux-amd64.xz\n"), h)

    def test_agy_manifest(self):
        url = "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.3.2-1/linux-x64/cli.tar.gz"
        m = {"version": "1.3.2", "url": url, "sha512": "f" * 128}
        self.assertEqual(bv.parse_agy(m), ("1.3.2", url, "f" * 128))

    def claude_manifest(self, **over):
        doc = {"version": "2.1.292", "platforms": {
            "linux-x64": {"binary": "claude", "checksum": "a" * 64, "size": 1},
            "linux-arm64": {"binary": "claude", "checksum": "b" * 64, "size": 1},
            "darwin-arm64": {"binary": "claude", "checksum": "c" * 64, "size": 1}}}
        doc.update(over)
        return doc

    def test_claude_manifest_gives_both_linux_checksums(self):
        self.assertEqual(bv.parse_claude_manifest(self.claude_manifest(), "2.1.292"), {
            "CLAUDE_CODE_VERSION": "2.1.292",
            "CLAUDE_CODE_SHA256_AMD64": "a" * 64, "CLAUDE_CODE_SHA256_ARM64": "b" * 64})

    def test_claude_manifest_for_another_version_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_claude_manifest(self.claude_manifest(version="2.1.291"), "2.1.292")

    def test_claude_manifest_without_a_platform_is_refused(self):
        doc = self.claude_manifest()
        del doc["platforms"]["linux-arm64"]
        with self.assertRaises(bv.LookupFailed):
            bv.parse_claude_manifest(doc, "2.1.292")

    def test_claude_manifest_with_a_bad_checksum_is_refused(self):
        doc = self.claude_manifest()
        doc["platforms"]["linux-x64"]["checksum"] = "A" * 64
        with self.assertRaises(bv.LookupFailed):
            bv.parse_claude_manifest(doc, "2.1.292")

    def test_node_index_picks_newest_of_the_major(self):
        doc = [{"version": "v28.0.0"}, {"version": "v26.14.0-rc.1"}, {"version": "v26.9.1"},
               {"version": "v26.13.0"}, {"version": "v24.22.2"}, {"version": "v26.99.0\n"}]
        self.assertEqual(bv.parse_node_index(doc, 26), "26.13.0")

    def test_node_index_with_an_unexpected_shape_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_index({"version": "v26.13.0"}, 26)
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_index(["v26.13.0"], 26)

    def test_node_index_skips_entries_that_are_not_objects(self):
        self.assertEqual(bv.parse_node_index(["junk", {"version": "v26.13.0"}], 26), "26.13.0")

    def test_node_index_without_the_major_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_index([{"version": "v24.22.2"}], 26)

    def test_node_shasums_gives_both_linux_hashes(self):
        text = ("%s  node-v26.13.0-linux-arm64.tar.xz\n%s  node-v26.13.0-linux-x64.tar.xz\n"
                "%s  node-v26.13.0-darwin-arm64.tar.gz\n"
                "%s  node-v26.13.0-linux-x64-musl.tar.xz\n%s  node-v26.13.0-linux-x64.tar.xz.sig\n"
                "%s  node-v26.13.01-linux-x64.tar.xz\n%s  *node-v26.13.0-linux-x64.tar.xz\n"
                ) % ("a" * 64, "b" * 64, "c" * 64, "d" * 64, "d" * 64, "d" * 64, "d" * 64)
        self.assertEqual(bv.parse_node_shasums(text, "26.13.0"),
                         {"NODE_VERSION": "26.13.0", "NODE_SHA256_AMD64": "b" * 64, "NODE_SHA256_ARM64": "a" * 64})

    def test_node_shasums_missing_an_arch_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_shasums("%s  node-v26.13.0-linux-x64.tar.xz\n" % ("b" * 64), "26.13.0")

    def test_node_shasums_with_a_bad_hash_is_refused(self):
        text = "%s  node-v26.13.0-linux-x64.tar.xz\n%s  node-v26.13.0-linux-arm64.tar.xz\n" % ("B" * 64, "a" * 64)
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_shasums(text, "26.13.0")

    def test_node_resolver_is_registered(self):
        self.assertIn(bv.r_node, bv.RESOLVERS)


@unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
class SignatureTests(unittest.TestCase):
    """verify_signature against two keys made for the test: "release" is the pinned key."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls.env = dict(os.environ, GNUPGHOME=cls.home)
        cls.data = b'{"version": "2.1.292"}'
        cls.data_file = os.path.join(cls.home, "data")
        with open(cls.data_file, "wb") as f:
            f.write(cls.data)
        cls.fpr, cls.key, cls.sig = {}, {}, {}
        for name in ("release", "other"):
            cls.fpr[name] = cls.make_key(name)
            cls.key[name] = cls.gpg("--armor", "--export", cls.fpr[name])
            cls.sig[name] = cls.gpg("--local-user", cls.fpr[name], "--detach-sign", "--output", "-",
                                    cls.data_file)

    @classmethod
    def gpg(cls, *args):
        cmd = ["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase", ""] + list(args)
        return subprocess.run(cmd, env=cls.env, check=True, capture_output=True).stdout

    @classmethod
    def make_key(cls, name):
        uid = "Test %s <%s@example.com>" % (name, name)
        cls.gpg("--quick-gen-key", uid, "ed25519", "sign", "never")
        out = cls.gpg("--with-colons", "--fingerprint", uid).decode()
        return [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr")][0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    def test_good_signature_passes(self):
        bv.verify_signature(self.data, self.sig["release"], self.key["release"], self.fpr["release"])

    def test_changed_data_fails(self):
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data + b" ", self.sig["release"], self.key["release"], self.fpr["release"])

    def test_key_with_another_fingerprint_fails(self):
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, self.sig["release"], self.key["release"], "0" * 40)

    def test_signature_by_a_second_key_in_the_key_file_fails(self):
        keys = self.key["release"] + self.key["other"]
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, self.sig["other"], keys, self.fpr["release"])

    def test_key_file_with_two_keys_fails(self):
        keys = self.key["release"] + self.key["other"]
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, self.sig["release"], keys, self.fpr["release"])

    def test_any_key_in_the_set_may_sign(self):
        keys = self.key["release"] + self.key["other"]
        both = (self.fpr["release"], self.fpr["other"])
        bv.verify_signature(self.data, self.sig["other"], keys, both)

    def test_key_file_must_hold_exactly_the_set(self):
        keys = self.key["release"] + self.key["other"]
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, self.sig["release"], keys, (self.fpr["release"], "0" * 40))

    def test_signature_by_a_key_outside_the_file_fails(self):
        # gpg refuses it for lack of the public key, before the signer-in-set check runs.
        keys = self.key["release"] + self.key["other"]
        third = self.make_key("third")
        sig = self.gpg("--local-user", third, "--detach-sign", "--output", "-", self.data_file)
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, sig, keys, (self.fpr["release"], self.fpr["other"]))

    def test_expired_key_is_refused_naming_expkeysig(self):
        at = "20200101T000000!"
        uid = "Test expired <expired@example.com>"
        self.gpg("--faked-system-time", at, "--quick-gen-key", uid, "ed25519", "sign", "1d")
        out = self.gpg("--with-colons", "--fingerprint", uid).decode()
        fpr = [l.split(":")[9] for l in out.splitlines() if l.startswith("fpr")][0]
        sig = self.gpg("--faked-system-time", at, "--local-user", fpr, "--detach-sign", "--output", "-",
                       self.data_file)
        with self.assertRaises(bv.LookupFailed) as ctx:
            bv.verify_signature(self.data, sig, self.gpg("--armor", "--export", fpr), (fpr,))
        self.assertIn("EXPKEYSIG", str(ctx.exception))

    def test_signing_subkey_reports_its_primary(self):
        # Some Node releasers sign with a subkey (release-keys README).
        primary = self.make_key("withsub")
        self.gpg("--quick-add-key", primary, "ed25519", "sign", "never")
        sub = [l.split(":")[4] for l in self.gpg("--with-colons", "--list-keys", primary).decode().splitlines()
               if l.startswith("sub")][0]
        sig = self.gpg("--local-user", sub + "!", "--detach-sign", "--output", "-", self.data_file)
        bv.verify_signature(self.data, sig, self.gpg("--armor", "--export", primary), (primary,))


def primary_fingerprints(path):
    """Primary key fingerprints of a key file, listed from a temporary GNUPGHOME."""
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, GNUPGHOME=home)
        gpg = ["gpg", "--batch", "--no-tty"]
        subprocess.run(gpg + ["--import", path], env=env, check=True, capture_output=True)
        out = subprocess.run(gpg + ["--with-colons", "--fingerprint"], env=env, check=True,
                             capture_output=True, text=True).stdout
    lines = out.splitlines()
    return [lines[i + 1].split(":")[9] for i, line in enumerate(lines)
            if line.startswith("pub:") and i + 1 < len(lines) and lines[i + 1].startswith("fpr:")]


class HelperTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
    def test_node_keyring_holds_exactly_the_pinned_fingerprints(self):
        # Imports NODE_KEYRING into a temporary GNUPGHOME and lists its primary fingerprints.
        self.assertEqual(sorted(primary_fingerprints(bv.NODE_KEYRING)), sorted(bv.NODE_KEY_FINGERPRINTS))

    def test_codex_uses_the_complete_package_asset(self):
        self.assertEqual(bv.codex_asset("aarch64"), "codex-package-aarch64-unknown-linux-musl.tar.gz")

    def test_hub_ref(self):
        self.assertEqual(bv.hub_ref("library/python", "3.14-slim", {"digest": "sha256:" + "a" * 64}),
                         "docker.io/library/python:3.14-slim@sha256:" + "a" * 64)

    def test_rewrite_image_ref_in_manifest(self):
        old = "docker.io/library/python:3.14-slim@sha256:" + "a" * 64
        new = "docker.io/library/python:3.14-slim@sha256:" + "b" * 64
        text = "      containers:\n        - image: %s\n          command: [x]\n" % old
        self.assertEqual(bv.rewrite_image_ref(text, new), text.replace(old, new))

    def test_strip_v(self):
        self.assertEqual(bv.strip_v("v2.102.0"), "2.102.0")
        self.assertEqual(bv.strip_v("rust-v0.162.0"), "0.162.0")
        self.assertEqual(bv.strip_v("0.12.24"), "0.12.24")


class ValidationTests(unittest.TestCase):
    def test_checksum_must_be_hex(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_checksum_file("<html>not found</html>\n")

    def test_empty_digest_rejected(self):
        release = {"tag_name": "v1", "assets": [{"name": "a", "digest": "sha256:"}]}
        with self.assertRaises(bv.LookupFailed):
            bv.asset_sha256(release, "a", fetch_text=lambda url: "")

    def test_agy_url_must_be_google_storage_and_hex(self):
        good = {"version": "1.3.2", "url": "https://storage.googleapis.com/antigravity-public/x/1.3.2/a.tar.gz",
                "sha512": "f" * 128}
        self.assertEqual(bv.parse_agy(good)[0], "1.3.2")
        with self.assertRaises(bv.LookupFailed):
            bv.parse_agy(dict(good, url="https://example.com/a.tar.gz"))
        with self.assertRaises(bv.LookupFailed):
            bv.parse_agy(dict(good, sha512="ff"))

    def test_agy_url_cannot_leave_the_bucket(self):
        # curl collapses "." and ".." segments, so these would fetch from another bucket.
        good = {"version": "1.3.2", "url": "https://storage.googleapis.com/antigravity-public/x/1.3.2/a.tar.gz",
                "sha512": "f" * 128}
        base = "https://storage.googleapis.com/antigravity-public/"
        bad = [
            base + "../attacker-bucket/cli_linux_x64.tar.gz",
            base + "x/../../attacker-bucket/a.tar.gz",
            base + "./a.tar.gz",
            base + "x/./a.tar.gz",
            base + "x/..",
            base + "%2e%2e/attacker-bucket/a.tar.gz",
            base + "%2E%2E/attacker-bucket/a.tar.gz",
            base + "x%2f..%2fa.tar.gz",
            base + "x//a.tar.gz",
            base + "a.tar.gz?x=1",
            base + "a.tar.gz#frag",
            base,
            "https://storage.googleapis.com/antigravity-publicx/a.tar.gz",
            "https://user@storage.googleapis.com/antigravity-public/a.tar.gz",
            "https://storage.googleapis.com:8443/antigravity-public/a.tar.gz",
            "http://storage.googleapis.com/antigravity-public/a.tar.gz",
        ]
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(bv.LookupFailed):
                    bv.parse_agy(dict(good, url=url))
                self.assertIsNotNone(bv.invalid("AGY_URL_AMD64", url))
        self.assertIsNone(bv.invalid("AGY_URL_AMD64", good["url"]))

    def test_node_pins_are_accepted(self):
        self.assertIsNone(bv.invalid("NODE_VERSION", "26.13.0"))
        self.assertIsNone(bv.invalid("NODE_SHA256_AMD64", "b" * 64))


class WriteTests(unittest.TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as f:
            f.write("A=1\n")
            self.path = f.name

    def tearDown(self):
        os.unlink(self.path)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def test_failure_leaves_file_untouched(self):
        def boom():
            raise bv.LookupFailed("network down")

        self.assertEqual(bv.main(["--file", self.path], resolvers=[boom]), 1)
        self.assertEqual(self.read(), "A=1\n")

    def test_failure_after_a_success_leaves_file_untouched(self):
        def ok():
            return {"A": "2"}

        def boom():
            raise bv.LookupFailed("network down")

        self.assertEqual(bv.main(["--file", self.path], resolvers=[ok, boom]), 1)
        self.assertEqual(self.read(), "A=1\n")

    def test_unexpected_error_is_a_clean_failure(self):
        def broken():
            return {}["missing"]

        self.assertEqual(bv.main(["--file", self.path], resolvers=[broken]), 1)
        self.assertEqual(self.read(), "A=1\n")

    def test_unknown_only_name_is_rejected(self):
        self.assertEqual(bv.main(["--file", self.path, "--only", "r_nope"]), 2)
        self.assertEqual(self.read(), "A=1\n")

    def test_success_updates_file(self):
        self.assertEqual(bv.main(["--file", self.path], resolvers=[lambda: {"GO_VERSION": "1.27.3"}]), 0)
        self.assertEqual(self.read(), "A=1\nGO_VERSION=1.27.3\n")

    def test_value_that_could_run_code_is_refused(self):
        # Shell scripts source versions.env, so upstream text must not reach it raw.
        bad = [
            {"AGY_URL_AMD64": "https://storage.googleapis.com/antigravity-public/$(touch /tmp/x)/a.tgz"},
            {"GO_VERSION": "1.27.3;id"},
            {"GH_VERSION": "2.103.1`id`"},
            {"BASE_IMAGE": "docker.io/library/ubuntu:26.04@sha256:" + "a" * 63},
            {"APT_SNAPSHOT": "20261008"},
            {"GO_SHA256_AMD64": "A" * 64},
            {"AGY_SHA512_AMD64": "a" * 127},
            {"OPENCODE_INTEGRITY_AMD64": "sha512-abc def"},
            {"NEW_THING": "1"},
        ]
        for update in bad:
            with self.subTest(update=update):
                self.assertEqual(bv.main(["--file", self.path], resolvers=[lambda u=update: u]), 1)
                self.assertEqual(self.read(), "A=1\n")

    @unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
    def test_node_with_a_bad_signature_leaves_file_untouched(self):
        shasums = ("%s  node-v26.99.0-linux-x64.tar.xz\n%s  node-v26.99.0-linux-arm64.tar.xz\n"
                   % ("b" * 64, "a" * 64)).encode()
        err = io.StringIO()
        with patch.object(bv, "fetch_json", return_value=[{"version": "v26.99.0"}]) as fj, \
                patch.object(bv, "fetch_bytes", side_effect=[shasums, b"not a signature"]) as fb, \
                contextlib.redirect_stderr(err):
            self.assertEqual(bv.main(["--file", self.path, "--only", "r_node"]), 1)
        fj.assert_called_once_with("https://nodejs.org/dist/index.json")
        self.assertEqual(fb.call_args_list, [call("https://nodejs.org/dist/v26.99.0/SHASUMS256.txt"),
                                             call("https://nodejs.org/dist/v26.99.0/SHASUMS256.txt.sig")])
        self.assertIn("signature", err.getvalue())
        self.assertEqual(self.read(), "A=1\n")

    def test_current_pins_pass_validation(self):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "..", "versions.env")) as f:
            for key, value in bv.values(bv.parse_env(f.read())).items():
                with self.subTest(key=key):
                    self.assertIsNone(bv.invalid(key, value))


NOW = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=datetime.timezone.utc)


def iso(days_before_now):
    return (NOW - datetime.timedelta(days=days_before_now)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class PickVersionTests(unittest.TestCase):
    def packument(self, versions, latest):
        return {"dist-tags": {"latest": latest},
                "versions": {v: dict(extra, version=v) for v, (_, extra) in versions.items()},
                "time": dict({"created": iso(400), "modified": iso(0)},
                             **{v: iso(age) for v, (age, _) in versions.items()})}

    def test_newest_version_at_least_seven_days_old(self):
        doc = self.packument({"1.0.0": (30, {}), "1.1.0": (8, {}), "1.2.0": (3, {}),
                              "1.3.0-beta.1": (10, {}), "1.1.5": (9, {"deprecated": "broken"}),
                              "2.0.0": (20, {})}, latest="1.2.0")
        # 2.0.0 is above dist-tags.latest, 1.2.0 is too young, 1.1.5 is deprecated, 1.3.0-beta.1 is a prerelease.
        self.assertEqual(bv.pick_version(doc, NOW), "1.1.0")

    def test_exactly_seven_days_qualifies(self):
        doc = self.packument({"1.0.0": (7, {})}, latest="1.0.0")
        self.assertEqual(bv.pick_version(doc, NOW), "1.0.0")

    def test_no_qualifying_version_fails(self):
        doc = self.packument({"1.0.0": (2, {}), "1.1.0-rc.1": (30, {})}, latest="1.0.0")
        with self.assertRaises(bv.LookupFailed):
            bv.pick_version(doc, NOW)

    def test_version_without_a_time_entry_is_skipped(self):
        doc = self.packument({"1.0.0": (30, {}), "1.1.0": (30, {})}, latest="1.1.0")
        del doc["time"]["1.1.0"]
        self.assertEqual(bv.pick_version(doc, NOW), "1.0.0")

    def test_prerelease_latest_bounds_the_pick_below_its_release(self):
        # npm accepts these prerelease forms; agentainer's own release_version.version_key rejects
        # the first two (dev.N without a date, and a numeric identifier with a leading zero).
        for latest in ("1.0.0-dev.5", "1.0.0-beta.01", "1.0.0-rc.1", "1.0.0-alpha+build.7"):
            with self.subTest(latest=latest):
                doc = self.packument({"0.9.0": (30, {}), "0.10.0": (20, {}), "1.0.0": (10, {}),
                                      latest: (15, {}), "1.0.0-dev.4": (25, {})}, latest=latest)
                # 1.0.0 is above a 1.0.0 prerelease, and 0.10.0 sorts above 0.9.0.
                self.assertEqual(bv.pick_version(doc, NOW), "0.10.0")

    def test_numeric_order_and_stable_latest_with_prereleases_in_versions(self):
        doc = self.packument({"1.9.0": (30, {}), "1.10.0": (20, {}), "2.0.0-dev.5": (15, {}),
                              "2.0.0-rc.1": (10, {}), "1.10.1-beta.02": (9, {})}, latest="1.10.0")
        self.assertEqual(bv.pick_version(doc, NOW), "1.10.0")

    def test_npm_version_key(self):
        key = bv.npm_version_key
        self.assertGreater(key("1.10.0"), key("1.9.0"))
        self.assertGreater(key("2.0.0"), key("2.0.0-dev.5"))
        self.assertGreater(key("2.0.0-rc.1"), key("1.99.99"))
        self.assertEqual(key("1.2.3+build.1"), key("1.2.3"))
        for bad in ("1.2", "v1.2.3", "1.2.3-", "x", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                key(bad)


class NewInstallScriptsTests(unittest.TestCase):
    def test_reports_only_packages_newly_flagged(self):
        old = {"packages": {"": {}, "node_modules/a": {"version": "1.0.0", "hasInstallScript": True},
                            "node_modules/c": {"version": "1.0.0"}}}
        new = {"packages": {"": {}, "node_modules/x/node_modules/a": {"version": "1.1.0", "hasInstallScript": True},
                            "node_modules/@s/b": {"version": "1.0.0", "hasInstallScript": True},
                            "node_modules/c": {"version": "1.1.0"},
                            "node_modules/node-pty": {"version": "1.0.0", "hasInstallScript": True},
                            "node_modules/frida": {"version": "1.0.0", "hasInstallScript": True}}}
        self.assertEqual(bv.new_install_scripts(old, new), ["@s/b"])

    def test_empty_old_lockfile_reports_every_flagged_package(self):
        new = {"packages": {"node_modules/a": {"version": "1.0.0", "hasInstallScript": True},
                            "node_modules/b": {"version": "1.0.0"}}}
        self.assertEqual(bv.new_install_scripts({}, new), ["a"])


def openssl(*args):
    return subprocess.run(["openssl"] + list(args), check=True, capture_output=True).stdout


@unittest.skipUnless(shutil.which("openssl"), "openssl is not installed")
class RegistrySignatureTests(unittest.TestCase):
    """verify_registry_signature against P-256 keys made for the test."""

    NAME, VERSION, INTEGRITY = "@s/pkg", "1.2.3", "sha512-" + "A" * 86 + "=="

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.keys, cls.pem = {}, {}
        for keyid in ("SHA256:good", "SHA256:old", "SHA256:other"):
            pem = os.path.join(cls.dir, keyid.split(":")[1] + ".pem")
            openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", pem)
            der = openssl("ec", "-in", pem, "-pubout", "-outform", "DER")
            cls.pem[keyid] = pem
            cls.keys[keyid] = {"keyid": keyid, "keytype": "ecdsa-sha2-nistp256", "scheme": "ecdsa-sha2-nistp256",
                               "expires": None, "key": base64.b64encode(der).decode()}
        cls.keys["SHA256:old"]["expires"] = "2025-01-29T00:00:00.000Z"
        # "other" signs but is not pinned.
        cls.pinned = {k: v for k, v in cls.keys.items() if k != "SHA256:other"}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def sign(self, keyid, message=None):
        message = message or "%s@%s:%s" % (self.NAME, self.VERSION, self.INTEGRITY)
        path = os.path.join(self.dir, "message")
        with open(path, "w") as f:
            f.write(message)
        sig = openssl("dgst", "-sha256", "-sign", self.pem[keyid], path)
        return {"keyid": keyid, "sig": base64.b64encode(sig).decode()}

    def verify(self, signatures, integrity=None, published=None):
        bv.verify_registry_signature(self.NAME, self.VERSION, integrity or self.INTEGRITY, signatures,
                                     self.pinned, published=published)

    def test_valid_signature_passes(self):
        self.verify([self.sign("SHA256:good")])

    def test_unknown_keyid_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:other")])

    def test_changed_integrity_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:good")], integrity="sha512-" + "B" * 86 + "==")

    def test_signature_over_other_data_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:good", message="other@1.2.3:" + self.INTEGRITY)])

    def test_garbage_signature_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([{"keyid": "SHA256:good", "sig": "bm90IGEgc2lnbmF0dXJl"}])

    def test_empty_list_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([])

    def test_any_verifying_signature_with_a_known_keyid_passes(self):
        bad = self.sign("SHA256:good", message="other@1.2.3:" + self.INTEGRITY)
        self.verify([self.sign("SHA256:other"), bad, self.sign("SHA256:good")])

    def test_expiring_key_passes_for_a_version_published_before_expiry(self):
        published = lambda: datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
        self.verify([self.sign("SHA256:old")], published=published)

    def test_expiring_key_fails_for_a_version_published_after_expiry(self):
        published = lambda: datetime.datetime(2025, 1, 29, tzinfo=datetime.timezone.utc)
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:old")], published=published)

    def test_expiring_key_fails_without_a_publish_time(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:old")])

    def test_missing_publish_time_moves_on_to_the_next_signature(self):
        def published():
            raise bv.LookupFailed("unexpected registry time None")

        self.verify([self.sign("SHA256:old"), self.sign("SHA256:good")], published=published)
        with self.assertRaises(bv.LookupFailed) as ctx:
            self.verify([self.sign("SHA256:old")], published=published)
        self.assertIn("@s/pkg@1.2.3", str(ctx.exception))
        self.assertIn("unexpected registry time", str(ctx.exception))

    def test_check_lockfile_verifies_every_entry(self):
        integrity = self.INTEGRITY
        lock = {"lockfileVersion": 3, "packages": {
            "": {"name": "wrapper", "dependencies": {"@s/pkg": "1.2.3"}},
            "node_modules/@s/pkg": {"version": "1.2.3", "integrity": integrity,
                                    "resolved": "https://registry.npmjs.org/@s/pkg/-/pkg-1.2.3.tgz"},
            "node_modules/@s/pkg/node_modules/inner": {"version": "1.0.0", "inBundle": True},
            "node_modules/alias": {"name": "@s/pkg", "version": "1.2.3", "integrity": integrity,
                                   "resolved": "https://registry.npmjs.org/@s/pkg/-/pkg-1.2.3.tgz"},
            "node_modules/old": {"version": "1.2.3", "integrity": integrity,
                                 "resolved": "https://registry.npmjs.org/old/-/old-1.2.3.tgz"}}}
        good = self.sign("SHA256:good")
        self.NAME = "old"
        old = self.sign("SHA256:old")
        self.NAME = "@s/pkg"
        docs = {"https://registry.npmjs.org/@s/pkg/1.2.3": {"dist": {"integrity": integrity, "signatures": [good]}},
                "https://registry.npmjs.org/old/1.2.3": {"dist": {"integrity": integrity, "signatures": [old]}},
                "https://registry.npmjs.org/old": {"time": {"1.2.3": "2024-06-01T00:00:00.000Z"}}}
        fetched = []

        def fetch(url):
            fetched.append(url)
            return docs[url]

        bv.check_lockfile(lock, fetch_json=fetch, keys=self.pinned)
        self.assertEqual(sorted(set(fetched)), sorted(docs))
        docs["https://registry.npmjs.org/old"]["time"]["1.2.3"] = "2025-02-01T00:00:00.000Z"
        with self.assertRaises(bv.LookupFailed):
            bv.check_lockfile(lock, fetch_json=fetch, keys=self.pinned)


class CheckLockfileTests(unittest.TestCase):
    INTEGRITY = "sha512-" + "A" * 86 + "=="

    def lock(self, **entry):
        base = {"version": "1.0.0", "integrity": self.INTEGRITY,
                "resolved": "https://registry.npmjs.org/a/-/a-1.0.0.tgz"}
        base.update(entry)
        return {"packages": {"": {}, "node_modules/a": {k: v for k, v in base.items() if v is not None}}}

    def check(self, lock, dist):
        verify = patch.object(bv, "verify_registry_signature")
        with verify as verified:
            bv.check_lockfile(lock, fetch_json=lambda url: {"dist": dist}, keys={})
        return verified

    def test_registry_integrity_must_equal_the_lockfile(self):
        with self.assertRaises(bv.LookupFailed):
            self.check(self.lock(), {"integrity": "sha512-" + "B" * 86 + "==", "signatures": []})

    def test_matching_integrity_goes_to_the_signature_check(self):
        verified = self.check(self.lock(), {"integrity": self.INTEGRITY, "signatures": ["s"]})
        self.assertEqual(verified.call_args.args[:4], ("a", "1.0.0", self.INTEGRITY, ["s"]))

    def test_entry_without_integrity_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.check(self.lock(integrity=None), {"integrity": self.INTEGRITY, "signatures": []})

    def test_entry_resolved_outside_the_registry_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.check(self.lock(resolved="https://example.com/a-1.0.0.tgz"),
                       {"integrity": self.INTEGRITY, "signatures": []})

    def test_link_entry_is_refused(self):
        lock = self.lock()
        lock["packages"]["node_modules/b"] = {"resolved": "../b", "link": True}
        with self.assertRaises(bv.LookupFailed) as ctx:
            self.check(lock, {"integrity": self.INTEGRITY, "signatures": []})
        self.assertIn("node_modules/b", str(ctx.exception))

    def test_bundled_entry_is_covered_by_its_parent(self):
        lock = self.lock()
        lock["packages"]["node_modules/a/node_modules/inner"] = {"version": "2.0.0", "inBundle": True}
        fetched = []

        def fetch(url):
            fetched.append(url)
            return {"dist": {"integrity": self.INTEGRITY, "signatures": []}}

        with patch.object(bv, "verify_registry_signature") as verified:
            bv.check_lockfile(lock, fetch_json=fetch, keys={})
        self.assertEqual(fetched, ["https://registry.npmjs.org/a/1.0.0"])
        self.assertEqual(verified.call_count, 1)

    def test_entry_that_is_not_an_object_is_refused(self):
        lock = self.lock()
        lock["packages"]["node_modules/b"] = "1.0.0"
        with self.assertRaises(bv.LookupFailed):
            self.check(lock, {"integrity": self.INTEGRITY, "signatures": []})
        with self.assertRaises(bv.LookupFailed):
            self.check({"packages": []}, {})
        with self.assertRaises(bv.LookupFailed):
            self.check([], {})

    def test_registry_data_that_is_not_an_object_is_refused(self):
        for doc in ([], {"dist": []}, {"dist": {"integrity": self.INTEGRITY, "signatures": {}}}):
            with self.subTest(doc=doc):
                with patch.object(bv, "verify_registry_signature"), self.assertRaises(bv.LookupFailed):
                    bv.check_lockfile(self.lock(), fetch_json=lambda url, d=doc: d, keys={})

    def test_names_outside_npm_naming_rules_are_refused(self):
        for name in (".", "..", ".hidden", "_private", "@scope/..", "@../x", "a/b", "a" * 215):
            with self.subTest(name=name):
                with self.assertRaises(bv.LookupFailed):
                    self.check(self.lock(name=name), {"integrity": self.INTEGRITY, "signatures": []})
        # npm allows a scoped name to begin with a dot or an underscore.
        verified = self.check(self.lock(name="@scope/_x"), {"integrity": self.INTEGRITY, "signatures": []})
        self.assertEqual(verified.call_args.args[0], "@scope/_x")


CATALOG = "rootfs/usr/local/share/agentainer/extras"


class ExtrasTests(unittest.TestCase):
    """r_extras and main over a temporary repo copy with npm, the registry and check_lockfile mocked."""

    OLD_LOCK = {"lockfileVersion": 3, "packages": {"": {"dependencies": {"kandev": "1.0.0"}},
                                                   "node_modules/kandev": {"version": "1.0.0"}}}

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.env = os.path.join(self.dir, "versions.env")
        self.write("versions.env", "A=1\nKANDEV_VERSION=1.0.0\nOPENCHAMBER_VERSION=2.0.0\nREA_VERSION=3.0.0\n")
        for key, name, extra in bv.EXTRAS:
            pin = {"kandev": "1.0.0", "openchamber": "2.0.0", "rea": "3.0.0"}[extra]
            self.write("%s/%s/package.json" % (CATALOG, extra),
                       json.dumps({"private": True, "dependencies": {name: pin}}, indent=2) + "\n")
            self.write("%s/%s/package-lock.json" % (CATALOG, extra),
                       json.dumps(dict(self.OLD_LOCK, name=extra), indent=2) + "\n")
            self.write("%s/%s/extra.conf" % (CATALOG, extra), "description=x\n")
        self.latest = {"kandev": "1.1.0", "@openchamber/web": "2.1.0", "rea-agents": "3.1.0"}
        self.new_lock_extra = {}
        self.npm_calls = []
        self.registry_docs = {}
        self.lock_override = {}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def snapshot(self):
        out = {}
        for root, _, files in os.walk(self.dir):
            for name in files:
                path = os.path.join(root, name)
                with open(path, "rb") as f:
                    out[os.path.relpath(path, self.dir)] = f.read()
        return out

    def packument(self, url):
        if url in self.registry_docs:
            return self.registry_docs[url]
        name = url[len("https://registry.npmjs.org/"):]
        ver = self.latest[name]
        return {"dist-tags": {"latest": ver}, "versions": {ver: {"version": ver}}, "time": {ver: iso(10)}}

    def npm(self, argv, **kwargs):
        self.npm_calls.append((argv, kwargs))
        with open(os.path.join(kwargs["cwd"], "package.json")) as f:
            deps = json.load(f)["dependencies"]
        (name, ver), = deps.items()
        packages = {"": {"dependencies": deps}, "node_modules/" + name: {
            "version": ver, "integrity": "sha512-" + "A" * 86 + "==",
            "resolved": "https://registry.npmjs.org/%s/-/x-%s.tgz" % (name, ver)}}
        packages.update(self.new_lock_extra.get(name, {}))
        with open(os.path.join(kwargs["cwd"], "package-lock.json"), "w") as f:
            json.dump(self.lock_override.get(name, {"lockfileVersion": 3, "packages": packages}), f)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def run_main(self, argv=None, resolvers=None, check=None, real_check=False, github_actions=None):
        out, err = io.StringIO(), io.StringIO()
        environ = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
        if github_actions is not None:
            environ["GITHUB_ACTIONS"] = github_actions
        checker = (contextlib.nullcontext() if real_check
                   else patch.object(bv, "check_lockfile", side_effect=check))
        with patch.object(bv, "fetch_json", side_effect=self.packument), \
                patch.object(bv.subprocess, "run", side_effect=self.npm), \
                checker as checked, \
                patch.object(bv, "utcnow", return_value=NOW), \
                patch.dict(os.environ, environ, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = bv.main(["--file", self.env] + (argv or []), resolvers=resolvers)
        self.checked = checked
        return rc, out.getvalue(), err.getvalue()

    def read(self, rel):
        with open(os.path.join(self.dir, rel)) as f:
            return f.read()

    def test_extras_resolver_is_registered_and_its_pins_validate(self):
        self.assertIn(bv.r_extras, bv.RESOLVERS)
        self.assertEqual([e[0] for e in bv.EXTRAS], ["KANDEV_VERSION", "OPENCHAMBER_VERSION", "REA_VERSION"])
        self.assertEqual(bv.EXTRA_MIN_AGE_DAYS, 7)
        for key, _, _ in bv.EXTRAS:
            self.assertIsNone(bv.invalid(key, "0.98.0"))

    def test_registry_keys_file_pins_both_npm_keys(self):
        keys = bv.load_registry_keys(bv.NPM_KEYS)
        self.assertEqual(sorted(keys), ["SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U",
                                        "SHA256:jl3bwswu80PjjokCgh0o2w5c2U4LhQAE57gj9cz1kzA"])
        self.assertIsNone(keys["SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U"]["expires"])
        self.assertEqual(keys["SHA256:jl3bwswu80PjjokCgh0o2w5c2U4LhQAE57gj9cz1kzA"]["expires"],
                         "2025-01-29T00:00:00.000Z")

    def test_success_writes_pins_wrappers_and_lockfiles(self):
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        env = self.read("versions.env")
        self.assertIn("KANDEV_VERSION=1.1.0\n", env)
        self.assertIn("OPENCHAMBER_VERSION=2.1.0\n", env)
        self.assertIn("REA_VERSION=3.1.0\n", env)
        wrapper = json.loads(self.read(CATALOG + "/openchamber/package.json"))
        self.assertEqual(wrapper, {"private": True, "dependencies": {"@openchamber/web": "2.1.0"}})
        lock = json.loads(self.read(CATALOG + "/rea/package-lock.json"))
        self.assertEqual(lock["packages"]["node_modules/rea-agents"]["version"], "3.1.0")
        self.assertIn("extras kandev: lockfile regenerated", out)
        self.assertEqual(self.checked.call_count, 3)
        argv, kwargs = self.npm_calls[0]
        self.assertEqual(argv[:6], ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit",
                                    "--no-fund"])
        self.assertIn("--before=2026-10-25T12:00:00Z", argv)
        self.assertIn("--registry=https://registry.npmjs.org/", argv)
        self.assertTrue(any(a.startswith("--cache=") for a in argv))
        self.assertNotEqual(kwargs["cwd"], self.dir)
        self.assertEqual(env.splitlines()[0], "A=1")

    def test_failed_check_keeps_only_that_extras_pin_and_files(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("rea-agents@3.1.0: registry integrity differs from the lockfile")

        before = self.snapshot()
        rc, out, err = self.run_main(["--only", "r_extras"], check=check)
        self.assertEqual(rc, 0, err)
        after = self.snapshot()
        for rel in ("package.json", "package-lock.json", "extra.conf"):
            path = os.path.join(CATALOG, "rea", rel)
            self.assertEqual(after[path], before[path])
        self.assertIn(b"REA_VERSION=3.0.0\n", after["versions.env"])
        self.assertIn(b"KANDEV_VERSION=1.1.0\n", after["versions.env"])
        self.assertNotEqual(after[os.path.join(CATALOG, "kandev", "package-lock.json")],
                            before[os.path.join(CATALOG, "kandev", "package-lock.json")])
        self.assertIn("bump_versions: extras rea: rea-agents@3.1.0: registry integrity differs from the lockfile; "
                      "pin unchanged", err)

    def test_new_install_script_keeps_the_pin(self):
        self.new_lock_extra["kandev"] = {"node_modules/evil": {"version": "1.0.0", "hasInstallScript": True}}
        before = self.snapshot()
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        after = self.snapshot()
        self.assertIn(b"KANDEV_VERSION=1.0.0\n", after["versions.env"])
        for rel in ("package.json", "package-lock.json"):
            path = os.path.join(CATALOG, "kandev", rel)
            self.assertEqual(after[path], before[path])
        self.assertIn("extras kandev:", err)
        self.assertIn("evil", err)

    def test_candidate_not_newer_keeps_the_pin_without_running_npm(self):
        self.latest = {"kandev": "1.0.0", "@openchamber/web": "1.9.0", "rea-agents": "3.0.0"}
        before = self.snapshot()
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.npm_calls, [])

    def test_prerelease_pin_is_replaced_by_its_release(self):
        self.write("versions.env", "A=1\nKANDEV_VERSION=1.1.0-dev.5\nOPENCHAMBER_VERSION=2.0.0\nREA_VERSION=3.0.0\n")
        self.latest = {"kandev": "1.1.0", "@openchamber/web": "2.0.0", "rea-agents": "3.0.0"}
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertIn("KANDEV_VERSION: 1.1.0-dev.5 -> 1.1.0", out)
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))

    def test_downgrade_guard_orders_extras_pins_numerically(self):
        self.write("versions.env", "KANDEV_VERSION=1.10.0\n")
        rc, out, err = self.run_main(resolvers=[lambda: {"KANDEV_VERSION": "1.9.0"}])
        self.assertNotEqual(rc, 0)
        self.assertIn("resolver would downgrade KANDEV_VERSION", err)
        self.assertEqual(self.read("versions.env"), "KANDEV_VERSION=1.10.0\n")
        self.write("versions.env", "KANDEV_VERSION=2.0.0-dev.5\n")
        rc, out, err = self.run_main(resolvers=[lambda: {"KANDEV_VERSION": "1.99.0"}])
        self.assertNotEqual(rc, 0)
        self.assertIn("resolver would downgrade KANDEV_VERSION", err)
        self.write("versions.env", "KANDEV_VERSION=2.0.0-dev.5\n")
        rc, out, err = self.run_main(resolvers=[lambda: {"KANDEV_VERSION": "2.0.0"}])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read("versions.env"), "KANDEV_VERSION=2.0.0\n")

    def test_missing_catalog_or_pin_skips_that_extra(self):
        shutil.rmtree(os.path.join(self.dir, CATALOG, "openchamber"))
        self.write("versions.env", "A=1\nKANDEV_VERSION=1.0.0\nOPENCHAMBER_VERSION=2.0.0\n")
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertIn("extras openchamber:", err)
        self.assertIn("extras rea:", err)
        env = self.read("versions.env")
        self.assertIn("KANDEV_VERSION=1.1.0\n", env)
        self.assertNotIn("REA_VERSION", env)
        self.assertFalse(os.path.exists(os.path.join(self.dir, CATALOG, "openchamber")))
        self.assertEqual(len(self.npm_calls), 1)

    def test_verification_failure_is_recorded_and_other_pins_are_written(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("rea-agents@3.1.0: no registry signature verifies")

        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], check=check,
                                     github_actions="true")
        self.assertEqual(rc, 0, err)
        line = "extras rea: rea-agents@3.1.0: no registry signature verifies"
        with open(failures) as f:
            self.assertEqual(f.read(), line + "\n")
        self.assertIn("::warning::bump_versions: " + line + "\n", out)
        self.assertIn("\n" + line + "\n", "\n" + out)
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))
        self.assertIn("REA_VERSION=3.0.0\n", self.read("versions.env"))

    def test_failure_line_is_one_line_and_the_annotation_is_escaped(self):
        def check(lock, **kwargs):
            if "node_modules/kandev" in lock["packages"]:
                raise bv.LookupFailed("npm said\n100% wrong")

        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], check=check,
                                     github_actions="true")
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertEqual(f.read(), "extras kandev: npm said 100% wrong\n")
        self.assertIn("::warning::bump_versions: extras kandev: npm said 100%25 wrong\n", out)

    def test_warning_annotation_only_on_github_actions(self):
        def check(lock, **kwargs):
            raise bv.LookupFailed("bad")

        rc, out, err = self.run_main(["--only", "r_extras"], check=check)
        self.assertEqual(rc, 0, err)
        self.assertNotIn("::warning::", out)
        self.assertIn("extras kandev: bad\n", out)

    def test_routine_skips_leave_the_failures_file_empty(self):
        shutil.rmtree(os.path.join(self.dir, CATALOG, "openchamber"))
        self.latest["kandev"] = "1.0.0"
        self.registry_docs["https://registry.npmjs.org/rea-agents"] = {
            "dist-tags": {"latest": "3.1.0"}, "versions": {"3.1.0": {}}, "time": {"3.1.0": iso(2)}}
        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], github_actions="true")
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertEqual(f.read(), "")
        self.assertNotIn("extras", out)
        self.assertIn("extras openchamber:", err)
        self.assertIn("extras rea:", err)
        self.assertEqual(self.npm_calls, [])

    def test_failures_file_is_not_created_without_the_option(self):
        def check(lock, **kwargs):
            raise bv.LookupFailed("bad")

        rc, out, err = self.run_main(["--only", "r_extras"], check=check)
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(p for p in os.listdir(self.dir)), ["rootfs", "versions.env"])

    def test_malformed_data_is_a_verification_failure_for_that_extra_only(self):
        # A lockfile that is a list, and a registry document for one version that is a list.
        self.lock_override["kandev"] = []
        self.registry_docs["https://registry.npmjs.org/rea-agents/3.1.0"] = []
        self.registry_docs["https://registry.npmjs.org/@openchamber/web/2.1.0"] = {
            "dist": {"integrity": "sha512-" + "B" * 86 + "==", "signatures": []}}
        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], real_check=True)
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            lines = f.read().splitlines()
        self.assertEqual([line.split(":")[0] for line in lines],
                         ["extras kandev", "extras openchamber", "extras rea"])
        env = self.read("versions.env")
        for pin in ("KANDEV_VERSION=1.0.0", "OPENCHAMBER_VERSION=2.0.0", "REA_VERSION=3.0.0"):
            self.assertIn(pin + "\n", env)

    def test_unexpected_shape_inside_a_check_stays_with_that_extra(self):
        error = AttributeError("'list' object has no attribute 'get'")
        with patch.object(bv, "new_install_scripts", side_effect=[[], error, []]):
            rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertIn("extras openchamber: 'list' object has no attribute 'get'\n", out)
        env = self.read("versions.env")
        self.assertIn("KANDEV_VERSION=1.1.0\n", env)
        self.assertIn("OPENCHAMBER_VERSION=2.0.0\n", env)
        self.assertIn("REA_VERSION=3.1.0\n", env)

    def test_malformed_registry_times_are_failures(self):
        failures = os.path.join(self.dir, "failures.txt")
        for case, time_map in (("absent", None), ("empty", {}), ("not a string", {"3.1.0": 12345})):
            with self.subTest(case=case):
                doc = {"dist-tags": {"latest": "3.1.0"}, "versions": {"3.1.0": {}}}
                if time_map is not None:
                    doc["time"] = time_map
                self.registry_docs["https://registry.npmjs.org/rea-agents"] = doc
                rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures])
                self.assertEqual(rc, 0, err)
                with open(failures) as f:
                    lines = f.read().splitlines()
                self.assertEqual([line.split(":")[0] for line in lines], ["extras rea"])
                self.assertIn("REA_VERSION=3.0.0\n", self.read("versions.env"))

    def test_too_young_version_is_a_quiet_skip(self):
        self.registry_docs["https://registry.npmjs.org/rea-agents"] = {
            "dist-tags": {"latest": "3.1.0"}, "versions": {"3.1.0": {}}, "time": {"3.1.0": iso(2)}}
        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures])
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertNotIn("extras rea", f.read())
        self.assertIn("extras rea:", err)

    def test_failed_run_still_leaves_an_empty_failures_file(self):
        def boom():
            raise bv.LookupFailed("network down")

        failures = os.path.join(self.dir, "failures.txt")
        with open(failures, "w") as f:
            f.write("stale\n")
        rc, out, err = self.run_main(["--failures", failures], resolvers=[boom])
        self.assertEqual(rc, 1)
        with open(failures) as f:
            self.assertEqual(f.read(), "")
        os.unlink(failures)
        rc, out, err = self.run_main(["--failures", failures, "--only", "r_nope"])
        self.assertEqual(rc, 2)
        with open(failures) as f:
            self.assertEqual(f.read(), "")

    def test_failures_found_before_a_failed_run_still_reach_the_file(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("rea-agents@3.1.0: no registry signature verifies")

        def boom():
            raise bv.LookupFailed("network down")

        failures = os.path.join(self.dir, "failures.txt")
        before = self.snapshot()
        rc, out, err = self.run_main(["--failures", failures], resolvers=[bv.r_extras, boom], check=check)
        self.assertEqual(rc, 1)
        with open(failures) as f:
            self.assertEqual(f.read(), "extras rea: rea-agents@3.1.0: no registry signature verifies\n")
        after = self.snapshot()
        del after["failures.txt"]
        self.assertEqual(after, before)

    def test_unwritable_failures_file_is_a_clean_error(self):
        failures = os.path.join(self.dir, "missing-dir", "failures.txt")
        before = self.snapshot()
        rc, out, err = self.run_main(["--failures", failures, "--only", "r_extras"])
        self.assertEqual(rc, 2)
        self.assertIn("bump_versions: cannot write --failures %s: " % failures, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.npm_calls, [])

    def failing_report_write(self, failures):
        """Patch write_atomic so every write to failures after the first (the truncation) raises."""
        real = bv.write_atomic
        calls = []

        def write(path, text):
            if path == failures:
                calls.append(text)
                if len(calls) > 1:
                    raise OSError(28, "No space left on device")
            real(path, text)

        return patch.object(bv, "write_atomic", side_effect=write)

    def test_failures_file_write_error_after_failures_fails_the_run(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("rea-agents@3.1.0: no registry signature verifies")

        failures = os.path.join(self.dir, "failures.txt")
        with self.failing_report_write(failures):
            rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], check=check)
        self.assertEqual(rc, 2)
        self.assertIn("bump_versions: cannot write --failures %s: " % failures, err)
        self.assertIn("No space left on device", err)
        self.assertNotIn("Traceback", err)
        self.assertIn("extras rea: rea-agents@3.1.0: no registry signature verifies\n", out)
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))

    def test_failures_file_write_error_keeps_a_nonzero_exit_code(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("bad")

        def boom():
            raise bv.LookupFailed("network down")

        failures = os.path.join(self.dir, "failures.txt")
        with self.failing_report_write(failures):
            rc, out, err = self.run_main(["--failures", failures], resolvers=[bv.r_extras, boom], check=check)
        self.assertEqual(rc, 1)
        self.assertIn("bump_versions: cannot write --failures %s: " % failures, err)

    def test_failures_file_write_error_does_not_mask_an_exception(self):
        original = RuntimeError("original error")

        def bump(args, resolvers):
            bv.EXTRA_FILES.failures.append("extras rea: bad")
            raise original

        failures = os.path.join(self.dir, "failures.txt")
        with self.failing_report_write(failures), patch.object(bv, "bump", side_effect=bump):
            with self.assertRaises(RuntimeError) as caught:
                self.run_main(["--failures", failures])
        self.assertIs(caught.exception, original)

    def test_failures_file_write_error_without_failures_keeps_success(self):
        failures = os.path.join(self.dir, "failures.txt")
        with self.failing_report_write(failures):
            rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures])
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertEqual(f.read(), "")
        self.assertIn("bump_versions: cannot write --failures %s: " % failures, err)
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))

    def test_broken_stdout_still_writes_the_failures_file(self):
        class BrokenPipe(io.StringIO):
            def write(self, s):
                raise BrokenPipeError(32, "Broken pipe")

        def check(lock, **kwargs):
            if "node_modules/kandev" not in lock["packages"]:
                raise bv.LookupFailed("bad")

        failures = os.path.join(self.dir, "failures.txt")
        # bump prints progress to stdout too, so only the report runs against the broken stream.
        real_bump = bv.bump

        def bump(args, resolvers):
            rc = real_bump(args, resolvers)
            sys.stdout = BrokenPipe()
            return rc

        stdout = sys.stdout
        try:
            with patch.object(bv, "bump", side_effect=bump):
                rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], check=check,
                                             github_actions="true")
        finally:
            sys.stdout = stdout
        self.assertEqual(rc, 0, err)
        self.assertNotIn("Traceback", err)
        with open(failures) as f:
            self.assertEqual(f.read().splitlines(), ["extras openchamber: bad", "extras rea: bad"])

    def test_catalog_files_are_written_before_versions_env(self):
        written = []
        real = bv.write_atomic

        def record(path, text):
            written.append(os.path.relpath(path, self.dir))
            real(path, text)

        with patch.object(bv, "write_atomic", side_effect=record):
            rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(written), 7)
        self.assertEqual(written[-1], "versions.env")

    def test_failed_write_leaves_no_temp_file(self):
        target = os.path.join(self.dir, "versions.env")
        with patch.object(bv.os, "replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            bv.write_atomic(target, "A=2\n")
        self.assertEqual(sorted(os.listdir(self.dir)), ["rootfs", "versions.env"])
        self.assertEqual(self.read("versions.env").splitlines()[0], "A=1")

    def test_written_file_keeps_its_mode(self):
        target = os.path.join(self.dir, "versions.env")
        os.chmod(target, 0o644)
        bv.write_atomic(target, "A=2\n")
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o644)

    def test_failure_in_another_resolver_writes_nothing(self):
        def boom():
            raise bv.LookupFailed("network down")

        before = self.snapshot()
        rc, out, err = self.run_main(resolvers=[bv.r_extras, boom])
        self.assertEqual(rc, 1)
        self.assertEqual(self.snapshot(), before)
        # Files computed by the failed run are not written by the next one.
        rc, out, err = self.run_main(resolvers=[lambda: {}])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
