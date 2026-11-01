import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "..", "..", "rootfs", "usr", "local", "bin", "agentainer-mcp")
loader = importlib.machinery.SourceFileLoader("agentainer_mcp", SRC)
spec = importlib.util.spec_from_loader("agentainer_mcp", loader)
mcp = importlib.util.module_from_spec(spec)
loader.exec_module(mcp)

# Stub CLI: logs its argv and succeeds.
STUB = """#!/bin/sh
echo "$(basename "$0") $*" >> "$LOG"
exit 0
"""


class SyncBase(unittest.TestCase):
    """A temporary home and stub agent CLIs that log their arguments."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(os.path.join(self.home, ".agentainer"))
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "log")
        open(self.log, "w").close()
        for name in ("claude", "codex", "opencode", "agy"):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(STUB)
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        self.env = {"HOME": self.home, "PATH": self.bin + ":/usr/bin:/bin",
                    "LOG": self.log, "SECRET_TOKEN": "s3cr3t-value"}

    def write_mcp(self, servers):
        with open(os.path.join(self.home, ".agentainer", "mcp.json"), "w") as f:
            json.dump({"mcpServers": servers}, f)

    def calls(self):
        with open(self.log) as f:
            return f.read()

    def sync(self):
        return mcp.main(["sync"], env=self.env)

    def sync_err(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = self.sync()
        return rc, err.getvalue()

    def assert_added_elsewhere(self, name, agents):
        """Positive check that sync ran: NAME reached each of AGENTS."""
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json") or "{}")
        for agent in agents:
            self.assertIn(name, manifest.get(agent, []), agent)
        for agent in ("claude", "agy"):
            if agent in agents:
                self.assertIn(name, self.json_servers(agent))
        if "codex" in agents:
            self.assertIn("[mcp_servers.%s]" % name, self.read(".codex", "config.toml"))
        if "opencode" in agents:
            self.assertIn(name, self.opencode_servers())

    def read(self, *parts):
        path = os.path.join(self.home, *parts)
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            return f.read()

    def json_servers(self, agent):
        parts = ((".claude.json",) if agent == "claude" else (".gemini", "config", "mcp_config.json"))
        text = self.read(*parts)
        return json.loads(text).get("mcpServers", {}) if text else {}

    def opencode_servers(self):
        text = self.read(".config", "opencode", "opencode.json")
        return (json.loads(text).get("mcp") or {}).get("servers", {}) if text else {}


class SyncTests(SyncBase):
    def test_sync_restricts_files_that_receive_literal_credentials(self):
        for relative, text in ((".codex/config.toml", 'model = "mine"\n'),
                               (".config/opencode/opencode.json", "{}\n")):
            path = os.path.join(self.home, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as file:
                file.write(text)
            os.chmod(path, 0o644)
        self.write_mcp({"sample": {"command": "echo", "env": {"TOKEN": "fake-literal"}}})
        self.assertEqual(self.sync(), 0)
        for relative in (".codex/config.toml", ".config/opencode/opencode.json"):
            path = os.path.join(self.home, relative)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertIn("fake-literal", self.read(*relative.split("/")))

    def test_startup_skips_unchanged_successful_input_but_direct_sync_runs(self):
        self.write_mcp({"fs": {"command": "example"}})
        with mock.patch.object(mcp, "write_atomic", wraps=mcp.write_atomic) as writes:
            self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
            self.assertIn("fs", self.json_servers("claude"))
            first = writes.call_count
            self.assertGreater(first, 0)
            self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
            self.assertEqual(writes.call_count, first)
            self.assertEqual(self.sync(), 0)
            self.assertGreater(writes.call_count, first)

    def test_startup_removes_servers_and_stamp_after_input_is_deleted(self):
        self.write_mcp({"fs": {"command": "example"}})
        self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
        self.assertTrue(self.read(".agentainer", ".mcp-synced.sha256"))
        os.unlink(os.path.join(self.home, ".agentainer", "mcp.json"))
        self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertTrue(manifest)
        self.assertTrue(all(not names for names in manifest.values()))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".agentainer", ".mcp-synced.sha256")))
        with mock.patch.object(mcp, "write_atomic", wraps=mcp.write_atomic) as writes:
            self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
            writes.assert_not_called()

    def test_adds_servers_to_each_agent(self):
        self.write_mcp({"fs": {"command": "npx", "args": ["-y", "@example/fs"]}})
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.json_servers("claude")["fs"],
                         {"type": "stdio", "command": "npx", "args": ["-y", "@example/fs"], "env": {}})
        self.assertEqual(self.json_servers("agy")["fs"],
                         {"command": "npx", "args": ["-y", "@example/fs"], "env": {}, "disabled": False})
        self.assertIn('[mcp_servers.fs]\ncommand = "npx"\nargs = ["-y", "@example/fs"]', self.read(".codex", "config.toml"))
        self.assertEqual(self.opencode_servers()["fs"], {"type": "local", "command": ["npx", "-y", "@example/fs"]})
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertEqual(manifest, {"agy": ["fs"], "claude": ["fs"], "codex": ["fs"], "opencode": ["fs"]})

    def test_config_write_error_does_not_log_credentials(self):
        self.write_mcp({"web": {"url": "https://mcp.example.com", "headers": {"X-Key": "literal-secret-123"}}})
        original = mcp.write_atomic

        def fail(path, text, **kwargs):
            if path == os.path.join(self.home, ".claude.json"):
                raise OSError("bad config: " + text)
            return original(path, text, **kwargs)

        err = io.StringIO()
        with mock.patch.object(mcp, "write_atomic", side_effect=fail):
            with contextlib.redirect_stderr(err):
                self.assertEqual(self.sync(), 1)
        self.assertIn("claude: not updated (OSError)", err.getvalue())
        self.assertNotIn("literal-secret-123", err.getvalue())

    def agy_config(self, text):
        os.makedirs(os.path.join(self.home, ".gemini", "config"), exist_ok=True)
        with open(os.path.join(self.home, ".gemini", "config", "mcp_config.json"), "w") as f:
            f.write(text)

    def test_agy_empty_config_has_no_servers(self):
        for text in ("", "  \n"):
            self.agy_config(text)
            self.write_mcp({"fs": {"command": "npx"}})
            self.assertEqual(self.sync(), 0)
            self.assertEqual(self.json_servers("agy")["fs"]["command"], "npx")
            os.unlink(os.path.join(self.home, ".agentainer", "mcp-managed.json"))

    def test_agy_broken_config_is_left_alone(self):
        self.agy_config("{not json")
        self.write_mcp({"fs": {"command": "npx"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 1)
        self.assertEqual(self.read(".gemini", "config", "mcp_config.json"), "{not json")
        self.assertIn("agy: not updated", err)
        self.assert_added_elsewhere("fs", ("claude", "codex", "opencode"))

    def test_removes_only_managed(self):
        self.write_mcp({"a": {"command": "x"}, "b": {"command": "y"}})
        self.assertEqual(self.sync(), 0)
        self.write_mcp({"a": {"command": "x"}})
        self.assertEqual(self.sync(), 0)
        for agent in ("claude", "agy"):
            self.assertEqual(sorted(self.json_servers(agent)), ["a"])
            self.assertEqual(self.json_servers(agent)["a"]["command"], "x")
        self.assertIn("[mcp_servers.a]", self.read(".codex", "config.toml"))
        self.assertNotIn("[mcp_servers.b]", self.read(".codex", "config.toml"))
        self.assertEqual(sorted(self.opencode_servers()), ["a"])

    def test_keeps_unmanaged_servers(self):
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            json.dump({"mcpServers": {"mine": {"type": "stdio", "command": "theirs"}}}, f)
        os.makedirs(os.path.join(self.home, ".codex"))
        with open(os.path.join(self.home, ".codex", "config.toml"), "w") as f:
            f.write('model = "x"\n\n[mcp_servers.mine]\ncommand = "theirs"\n')
        os.makedirs(os.path.join(self.home, ".config", "opencode"))
        with open(os.path.join(self.home, ".config", "opencode", "opencode.json"), "w") as f:
            json.dump({"update": "disable", "mcp": {"servers": {"mine": {"type": "local", "command": ["theirs"]}}}}, f)
        os.makedirs(os.path.join(self.home, ".gemini", "config"))
        with open(os.path.join(self.home, ".gemini", "config", "mcp_config.json"), "w") as f:
            json.dump({"mcpServers": {"mine": {"command": "theirs"}}}, f)
        self.write_mcp({"mine": {"command": "z"}, "other": {"command": "o"}})
        _, err = self.sync_err()
        for agent in ("claude", "agy"):
            self.assertEqual(self.json_servers(agent)["mine"]["command"], "theirs")
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        for agent in ("claude", "agy", "codex", "opencode"):
            self.assertNotIn("mine", manifest[agent])
        for agent in ("claude", "codex", "opencode", "agy"):
            self.assertIn("%s already has a server named mine" % agent, err)
        # A server without a conflict still reaches every agent.
        self.assertEqual(self.json_servers("claude")["other"]["command"], "o")
        self.assert_added_elsewhere("other", ("claude", "codex", "opencode", "agy"))
        toml = self.read(".codex", "config.toml")
        self.assertIn('command = "theirs"', toml)
        self.assertNotIn('command = "z"', toml)
        self.assertIn('model = "x"', toml)
        self.assertEqual(self.opencode_servers()["mine"]["command"], ["theirs"])
        self.assertIn('"update": "disable"', self.read(".config", "opencode", "opencode.json"))

    def test_malformed_json_changes_nothing(self):
        with open(os.path.join(self.home, ".agentainer", "mcp.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(self.sync(), 1)
        self.assertEqual(self.calls(), "")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".agentainer", "mcp-managed.json")))

    def test_list_works_with_malformed_mcp_json(self):
        with open(os.path.join(self.home, ".agentainer", "mcp.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(mcp.main(["list"], env=self.env), 0)

    def test_rejects_server_without_command_or_url(self):
        self.write_mcp({"bad": {"args": ["x"]}})
        self.assertEqual(self.sync(), 1)
        self.assertEqual(self.calls(), "")

    def test_never_writes_secret_values(self):
        self.write_mcp({"gh": {"command": "srv", "env": {"SECRET_TOKEN": "${SECRET_TOKEN}"}},
                        "web": {"url": "https://mcp.example.com/mcp",
                                "headers": {"Authorization": "Bearer ${SECRET_TOKEN}"}}})
        self.sync()
        # The servers were written, so the absence checks below look at real output.
        self.assertEqual(sorted(self.json_servers("claude")), ["gh", "web"])
        self.assertEqual(self.json_servers("claude")["web"]["headers"], {"Authorization": "Bearer ${SECRET_TOKEN}"})
        self.assertIn("[mcp_servers.gh]", self.read(".codex", "config.toml"))
        self.assertEqual(sorted(self.opencode_servers()), ["gh", "web"])
        self.assertNotIn("s3cr3t-value", self.calls())
        self.assertNotIn("s3cr3t-value", self.read(".codex", "config.toml"))
        self.assertNotIn("s3cr3t-value", self.read(".config", "opencode", "opencode.json"))

    def test_opencode_uses_its_env_syntax(self):
        self.write_mcp({"gh": {"command": "srv", "env": {"TOKEN": "${SECRET_TOKEN}"}}})
        self.sync()
        self.assertEqual(self.opencode_servers()["gh"]["environment"], {"TOKEN": "{env:SECRET_TOKEN}"})

    def test_opencode_remote_headers(self):
        self.write_mcp({"web": {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer ${SECRET_TOKEN}"}}})
        self.sync()
        self.assertEqual(self.opencode_servers()["web"],
                         {"type": "remote", "url": "https://mcp.example.com/mcp",
                          "headers": {"Authorization": "Bearer {env:SECRET_TOKEN}"}})

    def test_codex_env_reference_becomes_env_vars(self):
        self.write_mcp({"gh": {"command": "srv", "env": {"GH_TOKEN": "${GH_TOKEN}", "MODE": "ro"}}})
        self.sync()
        toml = self.read(".codex", "config.toml")
        self.assertIn('env_vars = ["GH_TOKEN"]', toml)
        self.assertIn('env = { "MODE" = "ro" }', toml)

    def test_codex_http_headers(self):
        self.write_mcp({"web": {"url": "https://mcp.example.com/mcp",
                                "headers": {"Authorization": "Bearer ${SECRET_TOKEN}",
                                            "X-Team": "${TEAM}", "X-Static": "1"}}})
        self.sync()
        toml = self.read(".codex", "config.toml")
        self.assertIn('bearer_token_env_var = "SECRET_TOKEN"', toml)
        self.assertIn('env_http_headers = { "X-Team" = "TEAM" }', toml)
        self.assertIn('http_headers = { "X-Static" = "1" }', toml)

    def test_agy_static_env_and_headers_written_references_dropped(self):
        self.write_mcp({"gh": {"command": "srv", "env": {"MODE": "ro", "T": "${SECRET_TOKEN}"}},
                        "web": {"url": "https://mcp.example.com/mcp", "headers": {"X-Static": "1"}}})
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.json_servers("agy")["gh"]["env"], {"MODE": "ro"})
        self.assertEqual(self.json_servers("agy")["web"]["headers"], {"X-Static": "1"})

class RobustnessTests(SyncBase):
    def test_stray_markers_are_replaced_and_user_settings_kept(self):
        # Codex rewrites config.toml and can drop or move the marker comments
        # ("codex mcp add" removes the begin marker). Damaged markers are replaced;
        # user settings stay.
        self.write_mcp({"sample": {"command": "echo"}})
        for markers in (mcp.MARK_BEGIN, mcp.MARK_END,
                        mcp.MARK_END + "\n" + mcp.MARK_BEGIN,
                        mcp.MARK_BEGIN + "\n" + mcp.MARK_BEGIN + "\n" + mcp.MARK_END):
            with self.subTest(markers=markers):
                original = 'model = "mine"\n' + markers + '\n[profiles.mine]\nmodel = "keep-me"\n'
                with open(self.codex_path(), "w") as file:
                    file.write(original)
                self.assertEqual(self.sync(), 0)
                toml = self.read(".codex", "config.toml")
                self.assertTrue(toml.startswith('model = "mine"\n'), toml)
                self.assertEqual(toml.count('[profiles.mine]\nmodel = "keep-me"\n'), 1)
                self.assertEqual(toml.count(mcp.MARK_BEGIN), 1)
                self.assertEqual(toml.count(mcp.MARK_END), 1)
                self.assertLess(toml.index(mcp.MARK_BEGIN), toml.index(mcp.MARK_END))
                self.assertEqual(toml.count("[mcp_servers.sample]"), 1)
                self.assertIn("[mcp_servers.sample]", self.block(toml))
                self.assertEqual(self.sync(), 0)
                self.assertEqual(self.read(".codex", "config.toml"), toml)

    def codex_path(self):
        os.makedirs(os.path.join(self.home, ".codex"), exist_ok=True)
        return os.path.join(self.home, ".codex", "config.toml")

    def test_user_tables_after_ours_survive_a_resync(self):
        self.write_mcp({"e": {"command": "x"}})
        self.sync()
        with open(self.codex_path(), "a") as f:
            f.write('\n[profiles.mine] # mine\nmodel = "keepme"\n\n[[skills.config]]\nname = "s"\n')
        self.write_mcp({"e": {"command": "y"}})
        self.sync()
        toml = self.read(".codex", "config.toml")
        self.assertIn('model = "keepme"', toml)
        self.assertIn("[[skills.config]]", toml)
        self.assertIn('command = "y"', toml)
        self.assertNotIn('command = "x"', toml)

    # Tables "codex plugin marketplace add" and "codex plugin add" write. Codex 0.163.0
    # puts them after our last table, before the end marker.
    MARKETPLACE = '[marketplaces.fixture-market]\nsource_type = "local"\nsource = "/fx/fixture-market"\n'
    PLUGIN = '[plugins."fixture-plugin@fixture-market"]\nenabled = true\n'
    CODEX_TABLES = MARKETPLACE + "\n" + PLUGIN

    def write_codex(self, text):
        with open(self.codex_path(), "w") as f:
            f.write(text)

    def put_in_block(self, tables, before=None):
        """Insert TABLES before the end marker, or before the line BEFORE when given."""
        text = self.read(".codex", "config.toml")
        self.assertEqual(text.count(mcp.MARK_END), 1)
        anchor = mcp.MARK_END if before is None else before
        self.assertEqual(text.count(anchor), 1)
        self.write_codex(text.replace(anchor, tables + ("" if before is None else "\n") + anchor))

    def block(self, text):
        b = text.find(mcp.MARK_BEGIN)
        return "" if b < 0 else text[b:text.find(mcp.MARK_END, b)]

    def assert_codex_tables_kept(self, toml):
        self.assertEqual(toml.count(self.MARKETPLACE), 1)
        self.assertEqual(toml.count(self.PLUGIN), 1)
        self.assertNotIn("[marketplaces.", self.block(toml))
        self.assertNotIn("[plugins.", self.block(toml))
        if mcp.tomllib is not None:
            data = mcp.tomllib.loads(toml)
            self.assertEqual(data["marketplaces"]["fixture-market"],
                             {"source_type": "local", "source": "/fx/fixture-market"})
            self.assertEqual(data["plugins"]["fixture-plugin@fixture-market"], {"enabled": True})

    def test_codex_tables_inside_our_block_survive_a_resync(self):
        user = 'model = "x"\n\n[profiles.mine]\nmodel = "keep"\n'
        self.write_codex(user)
        self.write_mcp({"e": {"url": "https://mcp.example.com/mcp"}})
        self.assertEqual(self.sync(), 0)
        self.put_in_block(self.CODEX_TABLES)
        self.write_mcp({"e": {"url": "https://mcp.example.org/mcp"}})
        self.assertEqual(self.sync(), 0)
        toml = self.read(".codex", "config.toml")
        self.assertTrue(toml.startswith(user), toml)
        self.assert_codex_tables_kept(toml)
        self.assertEqual(toml.count("[mcp_servers.e]"), 1)
        self.assertIn('url = "https://mcp.example.org/mcp"', self.block(toml))
        self.assertNotIn("example.com", toml)
        # A later sync with the same input leaves the file as it is.
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.read(".codex", "config.toml"), toml)

    def test_codex_tables_inside_our_block_survive_removing_mcp_json(self):
        self.write_mcp({"e": {"url": "https://mcp.example.com/mcp"}})
        self.assertEqual(self.sync(), 0)
        self.put_in_block(self.CODEX_TABLES)
        os.remove(os.path.join(self.home, ".agentainer", "mcp.json"))
        self.assertEqual(self.sync(), 0)
        toml = self.read(".codex", "config.toml")
        self.assert_codex_tables_kept(toml)
        self.assertNotIn(mcp.MARK_BEGIN, toml)
        self.assertNotIn(mcp.MARK_END, toml)
        self.assertNotIn("[mcp_servers.e]", toml)
        # Adding mcp.json back puts one block after the kept tables.
        self.write_mcp({"e": {"url": "https://mcp.example.org/mcp"}})
        self.assertEqual(self.sync(), 0)
        toml = self.read(".codex", "config.toml")
        self.assert_codex_tables_kept(toml)
        self.assertEqual(toml.count("[mcp_servers.e]"), 1)
        self.assertLess(toml.index(self.PLUGIN), toml.index(mcp.MARK_BEGIN))

    def test_codex_tables_anywhere_in_our_block_survive(self):
        for name, before in (("at the start", "[mcp_servers.e]"), ("between ours", "[mcp_servers.f]")):
            with self.subTest(name):
                self.write_codex("")
                self.write_mcp({"e": {"command": "a"}, "f": {"command": "b"}})
                self.assertEqual(self.sync(), 0)
                self.put_in_block(self.CODEX_TABLES + '\n[[skills.config]]\nname = "s"\n', before=before)
                self.write_mcp({"e": {"command": "c"}, "f": {"command": "d"}})
                self.assertEqual(self.sync(), 0)
                toml = self.read(".codex", "config.toml")
                self.assert_codex_tables_kept(toml)
                self.assertEqual(toml.count('[[skills.config]]\nname = "s"\n'), 1)
                self.assertNotIn("[[skills.", self.block(toml))
                for server, command in (("e", "c"), ("f", "d")):
                    self.assertEqual(toml.count("[mcp_servers.%s]" % server), 1)
                    self.assertIn('[mcp_servers.%s]\ncommand = "%s"' % (server, command), self.block(toml))

    def test_codex_mcp_add_inside_our_block_keeps_the_user_server(self):
        # Exact result of "codex mcp add mine -- echo hi" on a synced config, checked
        # with Codex 0.163.0: the begin marker is gone and the user's server sits
        # between our table and the end marker.
        self.write_codex('model = "m"\n')
        self.write_mcp({"e": {"url": "https://mcp.example.com/mcp"}})
        self.assertEqual(self.sync(), 0)
        self.write_codex('model = "m"\n\n[mcp_servers.e]\nurl = "https://mcp.example.com/mcp"\n\n'
                         '[mcp_servers.mine]\ncommand = "echo"\nargs = ["hi"]\n' + mcp.MARK_END + "\n")
        self.write_mcp({"e": {"url": "https://mcp.example.org/mcp"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        toml = self.read(".codex", "config.toml")
        self.assertTrue(toml.startswith('model = "m"\n'), toml)
        self.assertEqual(toml.count('[mcp_servers.mine]\ncommand = "echo"\nargs = ["hi"]\n'), 1)
        self.assertNotIn("[mcp_servers.mine]", self.block(toml))
        self.assertEqual(toml.count("[mcp_servers.e]"), 1)
        self.assertIn('url = "https://mcp.example.org/mcp"', self.block(toml))
        self.assertEqual((toml.count(mcp.MARK_BEGIN), toml.count(mcp.MARK_END)), (1, 1))
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertEqual(manifest["codex"], ["e"])

    def test_codex_block_from_before_the_manifest_is_still_ours(self):
        # A config written by an older sync, with no manifest entry for it.
        self.write_codex('model = "m"\n\n' + mcp.MARK_BEGIN + '\n[mcp_servers.e]\nurl = "https://mcp.example.com/mcp"\n'
                         + mcp.MARK_END + "\n")
        self.write_mcp({"e": {"url": "https://mcp.example.org/mcp"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        self.assertNotIn("did not add", err)
        toml = self.read(".codex", "config.toml")
        self.assertEqual(toml.count("[mcp_servers.e]"), 1)
        self.assertIn('url = "https://mcp.example.org/mcp"', self.block(toml))

    def test_comments_near_our_tables_are_kept(self):
        self.write_mcp({"e": {"command": "a"}})
        self.assertEqual(self.sync(), 0)
        self.put_in_block("# about the plugin\n" + self.PLUGIN)
        with open(self.codex_path(), "a") as f:
            f.write("# my closing note\n")
        self.write_mcp({"e": {"command": "b"}})
        self.assertEqual(self.sync(), 0)
        toml = self.read(".codex", "config.toml")
        self.assertEqual(toml.count("# about the plugin\n" + self.PLUGIN), 1)
        self.assertEqual(toml.count("# my closing note\n"), 1)
        self.assertIn('[mcp_servers.e]\ncommand = "b"', self.block(toml))
        # A comment after our last table, with nothing after it, is kept too.
        self.put_in_block("# note under our table\n")
        self.write_mcp({"e": {"command": "c"}})
        self.assertEqual(self.sync(), 0)
        toml = self.read(".codex", "config.toml")
        self.assertEqual(toml.count("# note under our table\n"), 1)
        self.assertIn('[mcp_servers.e]\ncommand = "c"', self.block(toml))

    def test_codex_env_sub_table_of_our_server_is_replaced(self):
        # "codex mcp add" rewrites an inline env = { ... } as an [mcp_servers.<name>.env]
        # table (seen with Codex 0.163.0); it is still our server's env.
        self.write_mcp({"a": {"command": "srv", "env": {"MODE": "ro"}}})
        self.assertEqual(self.sync(), 0)
        text = self.read(".codex", "config.toml").replace('env = { "MODE" = "ro" }\n', "")
        self.write_codex(text.replace(mcp.MARK_END, '\n[mcp_servers.a.env]\nMODE = "ro"\n' + mcp.MARK_END))
        self.write_mcp({"a": {"command": "srv", "env": {"MODE": "rw"}}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        toml = self.read(".codex", "config.toml")
        self.assertNotIn("[mcp_servers.a.env]", toml)
        self.assertEqual(toml.count('env = { "MODE" = "rw" }'), 1)
        self.assertNotIn('"ro"', toml)

    def test_marker_fallback_is_off_when_the_manifest_lists_codex_servers(self):
        self.write_mcp({"e": {"command": "a"}})
        self.assertEqual(self.sync(), 0)
        # The user puts their own server inside our markers.
        self.put_in_block('[mcp_servers.mine]\ncommand = "theirs"\n')
        self.write_mcp({"e": {"command": "b"}, "mine": {"command": "ours"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        toml = self.read(".codex", "config.toml")
        self.assertIn("codex already has a server named mine", err)
        self.assertEqual(toml.count('[mcp_servers.mine]\ncommand = "theirs"\n'), 1)
        self.assertNotIn('command = "ours"', toml)

    def test_marker_fallback_claims_only_servers_in_mcp_json(self):
        # No manifest: an older config whose markers also hold a user server.
        self.write_codex(mcp.MARK_BEGIN + '\n[mcp_servers.e]\ncommand = "a"\n\n[mcp_servers.mine]\ncommand = "theirs"\n'
                         + mcp.MARK_END + "\n")
        self.write_mcp({"e": {"command": "b"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        toml = self.read(".codex", "config.toml")
        self.assertEqual(toml.count('[mcp_servers.mine]\ncommand = "theirs"\n'), 1)
        self.assertEqual(toml.count("[mcp_servers.e]"), 1)
        self.assertIn('command = "b"', self.block(toml))

    def test_quoted_and_indented_spellings_of_our_table_are_rewritten(self):
        for header in ("[mcp_servers.'e']", '[mcp_servers."e"]', "[ mcp_servers . e ]"):
            with self.subTest(header):
                self.write_codex('model = "m"\n\n  ' + mcp.MARK_BEGIN + "\n" + header + '\ncommand = "a"\n'
                                 + mcp.MARK_END + "\n")
                self.write_mcp({"e": {"command": "b"}})
                rc, err = self.sync_err()
                self.assertEqual(rc, 0, err)
                toml = self.read(".codex", "config.toml")
                self.assertNotIn(header, toml)
                self.assertNotIn('command = "a"', toml)
                self.assertEqual(toml.count(mcp.MARK_BEGIN), 1)
                self.assertIn('[mcp_servers.e]\ncommand = "b"', self.block(toml))

    @unittest.skipIf(mcp.tomllib is None, "needs tomllib (Python 3.11+); tests/80-mcp.sh runs it in the image")
    def test_codex_settings_on_our_server_are_kept(self):
        # Keys from the Codex config reference that agentainer does not write.
        self.write_mcp({"e": {"url": "https://mcp.example.com/mcp"}})
        self.assertEqual(self.sync(), 0)
        self.put_in_block('enabled = false\nenabled_tools = ["search", "fetch"]\n\n'
                          '[mcp_servers.e.tools.search]\napproval_mode = "approve"\noutput_token_limit = 4000\n')
        self.write_mcp({"e": {"url": "https://mcp.example.org/mcp"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        toml = self.read(".codex", "config.toml")
        server = mcp.tomllib.loads(toml)["mcp_servers"]["e"]
        self.assertEqual(server, {"url": "https://mcp.example.org/mcp", "enabled": False,
                                  "enabled_tools": ["search", "fetch"],
                                  "tools": {"search": {"approval_mode": "approve", "output_token_limit": 4000}}})
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.read(".codex", "config.toml"), toml)
        # Removing the server from mcp.json removes its settings too.
        self.write_mcp({})
        self.assertEqual(self.sync(), 0)
        self.assertNotIn("mcp_servers", mcp.tomllib.loads(self.read(".codex", "config.toml")))

    @unittest.skipIf(mcp.tomllib is None, "needs tomllib (Python 3.11+); tests/80-mcp.sh runs it in the image")
    def test_codex_settings_keep_their_types_and_quoted_keys(self):
        self.write_mcp({"e": {"command": "a"}})
        self.assertEqual(self.sync(), 0)
        self.put_in_block('enabled = false\nstartup_timeout_sec = 12.5\nsince = 2026-01-02T03:04:05Z\n\n'
                          '[mcp_servers.e.tools."a.b"]\napproval_mode = "approve"\nlimit = 4000\n')
        self.write_mcp({"e": {"command": "b"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        server = mcp.tomllib.loads(self.read(".codex", "config.toml"))["mcp_servers"]["e"]
        self.assertIs(server["enabled"], False)
        self.assertIs(type(server["startup_timeout_sec"]), float)
        self.assertEqual(server["startup_timeout_sec"], 12.5)
        self.assertEqual(server["since"].isoformat(), "2026-01-02T03:04:05+00:00")
        self.assertEqual(server["tools"], {"a.b": {"approval_mode": "approve", "limit": 4000}})
        self.assertIs(type(server["tools"]["a.b"]["limit"]), int)

    @unittest.skipIf(mcp.tomllib is None, "needs tomllib (Python 3.11+); tests/80-mcp.sh runs it in the image")
    def test_codex_nan_elsewhere_does_not_block_the_sync(self):
        self.write_codex("ratio = nan\n")
        self.write_mcp({"e": {"command": "a"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        self.assertIn("ratio = nan", self.read(".codex", "config.toml"))

    @unittest.skipIf(mcp.tomllib is None, "needs tomllib (Python 3.11+); tests/80-mcp.sh runs it in the image")
    def test_codex_invalid_toml_is_reported_and_left_alone(self):
        self.write_codex("model = \n")
        self.write_mcp({"e": {"command": "a"}})
        rc, err = self.sync_err()
        self.assertNotEqual(rc, 0)
        self.assertIn("codex: config.toml is not valid TOML; nothing written", err)
        self.assertEqual(self.read(".codex", "config.toml"), "model = \n")

    @unittest.skipIf(mcp.tomllib is None, "needs tomllib (Python 3.11+); tests/80-mcp.sh runs it in the image")
    def test_codex_removing_an_own_key_mcp_json_does_not_set_warns(self):
        self.write_mcp({"a": {"command": "x"}})
        self.assertEqual(self.sync(), 0)
        self.put_in_block('\n[mcp_servers.a.env]\nUSERVAR = "keep"\n')
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        self.assertIn("codex: a: removed env, which mcp.json does not set; add it to mcp.json to keep it", err)
        self.assertNotIn("USERVAR", self.read(".codex", "config.toml"))

    def test_codex_header_check_is_fast_on_long_lines(self):
        # The header pattern runs on every line, including multi-line string content.
        import time
        start = time.monotonic()
        spaces = " " * 100000
        for line in ("[a" + spaces + "x", "[a" + spaces + "]x", "[" + "a." * 100000, '["' + "x" * 200000):
            self.assertIsNone(mcp.codex_header_parts(line))
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual(mcp.codex_header_parts('[ mcp_servers . "a]b" ] # [c]'), ["mcp_servers", "a]b"])
        self.assertEqual(mcp.codex_header_parts("[[mcp_servers.'x'.y]]"), ["mcp_servers", "x", "y"])

    def test_codex_user_table_with_a_bracket_in_a_quoted_key_is_kept(self):
        self.write_mcp({"e": {"command": "a"}})
        self.assertEqual(self.sync(), 0)
        with open(self.codex_path(), "a") as f:
            f.write('\n[profiles."x]y"]\nk = 1\n')
        self.write_mcp({"e": {"command": "b"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0, err)
        toml = self.read(".codex", "config.toml")
        self.assertEqual(toml.count('[profiles."x]y"]\nk = 1\n'), 1)
        self.assertIn('[mcp_servers.e]\ncommand = "b"', self.block(toml))

    @unittest.skipIf(mcp.tomllib is None, "needs tomllib (Python 3.11+); tests/80-mcp.sh runs it in the image")
    def test_codex_sync_refuses_a_write_that_would_drop_settings(self):
        self.write_mcp({"e": {"url": "https://mcp.example.com/mcp"}})
        self.assertEqual(self.sync(), 0)
        self.put_in_block(self.CODEX_TABLES)
        original = self.read(".codex", "config.toml")
        self.write_mcp({"e": {"url": "https://mcp.example.org/mcp"}})
        # A table removal that also drops a table it does not own must stop the write.
        real = mcp.codex_drop_owned
        with mock.patch.object(mcp, "codex_drop_owned",
                               lambda text, owned: real(text, owned).replace(self.PLUGIN, "")):
            rc, err = self.sync_err()
        self.assertNotEqual(rc, 0)
        self.assertIn("codex: config.toml would lose settings agentainer does not manage", err)
        self.assertEqual(self.read(".codex", "config.toml"), original)
        # Positive control: the same sync without the fault writes and keeps the tables.
        self.assertEqual(self.sync(), 0)
        self.assert_codex_tables_kept(self.read(".codex", "config.toml"))

    def test_user_server_in_other_toml_spellings_is_left_alone(self):
        for text in ('mcp_servers.foo.command = "theirs"\n',
                     '[mcp_servers]\nfoo = { command = "theirs" }\n',
                     '[mcp_servers."foo"]\ncommand = "theirs"\n'):
            with open(self.codex_path(), "w") as f:
                f.write(text)
            self.write_mcp({"foo": {"command": "ours"}, "bar": {"command": "ok"}})
            _, err = self.sync_err()
            toml = self.read(".codex", "config.toml")
            self.assertNotIn('"ours"', toml, text)
            self.assertIn('"theirs"', toml, text)
            self.assertIn("codex already has a server named foo", err, text)
            self.assertIn('[mcp_servers.bar]\ncommand = "ok"', toml, text)

    def test_non_bmp_characters_are_written_literally(self):
        self.write_mcp({"u": {"command": "srv", "args": ["\U0001F600", "a\x7fb"]}})
        self.sync()
        toml = self.read(".codex", "config.toml")
        self.assertIn("\U0001F600", toml)
        self.assertNotIn("\\ud83d", toml.lower())
        self.assertNotIn("\x7f", toml)

    def test_bad_value_types_are_rejected_before_any_change(self):
        for servers in ({"p": {"command": "srv", "env": {"PORT": 8080}}},
                        {"p": {"command": "srv", "args": "not-a-list"}},
                        {"p": {"url": "https://x.example.com", "headers": {"H": ["a"]}}}):
            open(self.log, "w").close()
            self.write_mcp(servers)
            self.assertEqual(self.sync(), 1)
            self.assertEqual(self.calls(), "")

    def test_one_agent_failing_does_not_lose_the_others(self):
        os.makedirs(os.path.join(self.home, ".config", "opencode"))
        with open(os.path.join(self.home, ".config", "opencode", "opencode.json"), "w") as f:
            f.write('{"mcp": []}')
        self.write_mcp({"k": {"command": "x"}})
        rc = self.sync()
        self.assertNotEqual(rc, 0)
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertEqual(manifest["claude"], ["k"])
        self.assertEqual(manifest["agy"], ["k"])
        # Removing k later removes it where it was added.
        self.write_mcp({})
        open(self.log, "w").close()
        self.sync()
        self.assertEqual(self.json_servers("claude"), {})
        self.assertEqual(self.json_servers("agy"), {})

    def test_failed_config_write_returns_nonzero(self):
        self.write_mcp({"k": {"command": "x"}})
        original = mcp.write_atomic

        def fail(path, text):
            if path == os.path.join(self.home, ".claude.json"):
                raise OSError("injected failure")
            return original(path, text)

        with mock.patch.object(mcp, "write_atomic", side_effect=fail):
            self.assertNotEqual(self.sync(), 0)
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertNotIn("k", manifest.get("claude", []))
        self.assertIn("k", manifest["agy"])

    def test_partial_reference_warns(self):
        import io
        import contextlib
        err = io.StringIO()
        self.write_mcp({"w": {"url": "https://x.example.com", "headers": {"X": "Token ${T}"}}})
        with contextlib.redirect_stderr(err):
            self.sync()
        self.assertIn("only exact ${NAME}", err.getvalue())

    def test_codex_bearer_reference_on_other_header_is_left_out(self):
        # Codex env_http_headers sends the variable's value as the whole header, so
        # "Bearer ${T}" on a header other than Authorization has no Codex spelling.
        self.write_mcp({"w": {"url": "https://x.example.com", "headers": {"X-Auth": "Bearer ${T}"}}})
        rc, err = self.sync_err()
        toml = self.read(".codex", "config.toml")
        self.assertNotIn("X-Auth", toml)
        self.assertNotIn("${T}", toml)
        self.assertIn("codex: header X-Auth on w", err)
        self.assertEqual(rc, 0)

    def test_sse_server_goes_to_claude_as_sse(self):
        self.write_mcp({"s": {"type": "sse", "url": "https://x.example.com/sse"}})
        rc, err = self.sync_err()
        self.assertEqual(self.json_servers("claude")["s"]["type"], "sse")
        self.assertNotIn("[mcp_servers.s]", self.read(".codex", "config.toml"))
        self.assertNotIn("s", self.json_servers("agy"))
        self.assertIn("codex: s uses SSE", err)
        self.assertIn("agy: s uses SSE", err)
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertEqual(manifest["claude"], ["s"])
        self.assertEqual(manifest["codex"], [])
        self.assertEqual(manifest["agy"], [])
        self.assertEqual(rc, 0)

    def test_http_type_is_accepted(self):
        self.write_mcp({"h": {"type": "http", "url": "https://x.example.com/mcp"},
                        "c": {"type": "stdio", "command": "srv"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0)
        self.assertNotIn("warning", err)
        self.assertEqual(self.json_servers("claude")["h"]["type"], "http")

    def test_bad_type_is_rejected(self):
        for s in ({"type": "sse", "command": "srv"}, {"type": "ws", "url": "wss://x.example.com"}):
            open(self.log, "w").close()
            self.write_mcp({"b": s})
            self.assertEqual(self.sync_err()[0], 1)
            self.assertEqual(self.calls(), "")

    def test_unknown_keys_warn(self):
        self.write_mcp({"c": {"command": "srv", "cwd": "/tmp", "timeout": 5, "disabled": True}})
        rc, err = self.sync_err()
        self.assertIn("c: cwd, disabled, timeout", err)
        self.assertEqual(self.json_servers("claude")["c"]["command"], "srv")

    def claude_json(self, data):
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def test_claude_conflict_reads_user_scope_only(self):
        # A project-scope server of the same name (in /workspace) is not a conflict.
        self.claude_json({"mcpServers": {"mine": {"type": "stdio", "command": "x"}},
                          "projects": {"/workspace": {"mcpServers": {"proj": {"command": "y"}}}}})
        self.write_mcp({"mine": {"command": "z"}, "proj": {"command": "z"}})
        self.sync()
        self.assertEqual(self.calls(), "")
        data = json.loads(self.read(".claude.json"))
        self.assertEqual(data["projects"]["/workspace"]["mcpServers"], {"proj": {"command": "y"}})
        self.assertEqual(self.json_servers("claude")["mine"]["command"], "x")
        self.assertEqual(self.json_servers("claude")["proj"]["command"], "z")

    def test_claude_conflict_honours_claude_config_dir(self):
        d = os.path.join(self.tmp, "cc")
        os.makedirs(d)
        with open(os.path.join(d, ".claude.json"), "w") as f:
            json.dump({"mcpServers": {"mine": {"command": "x"}}}, f)
        self.env["CLAUDE_CONFIG_DIR"] = d
        self.write_mcp({"mine": {"command": "z"}, "other": {"command": "o"}})
        _, err = self.sync_err()
        self.assertIn("claude already has a server named mine", err)
        with open(os.path.join(d, ".claude.json")) as f:
            servers = json.load(f)["mcpServers"]
        self.assertEqual(servers["mine"]["command"], "x")
        self.assertEqual(servers["other"]["command"], "o")
        self.assert_added_elsewhere("mine", ("agy", "codex", "opencode"))

    def test_unreadable_claude_json_is_left_alone(self):
        self.claude_json("{broken")
        self.write_mcp({"k": {"command": "z"}})
        _, err = self.sync_err()
        self.assertIn("claude: not updated", err)
        self.assertEqual(self.read(".claude.json"), "{broken")
        self.assert_added_elsewhere("k", ("agy", "codex", "opencode"))



class WriteAtomicTests(unittest.TestCase):
    def test_literal_credentials_make_existing_config_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.toml")
            with open(path, "w") as file:
                file.write("original")
            os.chmod(path, 0o644)
            mcp.write_atomic(path, "fake literal", private=True)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def tmpdir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        return d

    def test_another_writers_temp_file_does_not_block(self):
        # Two containers can share one home volume, so a fixed temp name can collide.
        d = self.tmpdir()
        path = os.path.join(d, "mcp-managed.json")
        os.mkdir(path + ".agentainer-tmp")
        mcp.write_atomic(path, "{}")
        with open(path) as f:
            self.assertEqual(f.read(), "{}")
        self.assertEqual(sorted(os.listdir(d)), ["mcp-managed.json", "mcp-managed.json.agentainer-tmp"])

    def test_keeps_the_mode_of_a_replaced_file(self):
        d = self.tmpdir()
        path = os.path.join(d, "config.toml")
        with open(path, "w") as f:
            f.write("old")
        os.chmod(path, 0o640)
        mcp.write_atomic(path, "new")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)

    def test_symlinked_file_stays_a_symlink(self):
        # A user who keeps config.toml in a dotfiles repo links it into place.
        d = self.tmpdir()
        os.mkdir(os.path.join(d, "dotfiles"))
        target = os.path.join(d, "dotfiles", "config.toml")
        with open(target, "w") as f:
            f.write("old")
        link = os.path.join(d, "config.toml")
        os.symlink(os.path.join("dotfiles", "config.toml"), link)
        mcp.write_atomic(link, "new")
        self.assertTrue(os.path.islink(link))
        with open(target) as f:
            self.assertEqual(f.read(), "new")
        self.assertEqual(sorted(os.listdir(os.path.join(d, "dotfiles"))), ["config.toml"])

    def test_syncs_data_before_rename(self):
        calls = []
        real_fsync, real_replace = os.fsync, os.replace
        os.fsync = lambda fd: (calls.append("fsync"), real_fsync(fd))[1]
        os.replace = lambda a, b: (calls.append("replace"), real_replace(a, b))[1]
        try:
            mcp.write_atomic(os.path.join(self.tmpdir(), "f"), "x")
        finally:
            os.fsync, os.replace = real_fsync, real_replace
        self.assertEqual(calls[:2], ["fsync", "replace"])

if __name__ == "__main__":
    unittest.main()
