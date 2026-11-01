import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
