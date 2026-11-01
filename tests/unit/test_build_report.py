import importlib.util
import io
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location(
    "build_report", os.path.join(HERE, "..", "..", "scripts", "build_report.py"))
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)


class BuildReportTests(unittest.TestCase):
    def test_major_updates_request_acknowledgement_without_blocking(self):
        old = self.write("HELM_VERSION=3.9.0\nGO_VERSION=1.26.0\nUV_VERSION=0.12.0\n")
        new = self.write("HELM_VERSION=4.0.0\nGO_VERSION=1.27.0\nUV_VERSION=0.13.0\n")
        out = br.major_updates(old, new)
        self.assertIn("### Major-version upgrades", out)
        self.assertIn("| HELM_VERSION | 3.9.0 | 4.0.0 |", out)
        self.assertIn("- [ ]", out)
        self.assertNotIn("GO_VERSION", out)
        self.assertNotIn("UV_VERSION", out)

    def test_minor_update_has_no_major_notice(self):
        self.assertEqual(br.major_updates(self.write("GO_VERSION=1.26.0\n"),
                                         self.write("GO_VERSION=1.27.0\n")), "")

    def write(self, text):
        f = tempfile.NamedTemporaryFile("w", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_versions_lists_pinned_versions_and_key_packages(self):
        path = self.write(json.dumps({
            "pins": {"CLAUDE_CODE_VERSION": "2.1.287", "GO_VERSION": "1.27.2",
                     "NODE_VERSION": "26.13.0",
                     "CODEX_SHA256_AMD64": "ab" * 32, "APT_SNAPSHOT": "20261008T000000Z",
                     "BASE_IMAGE": "docker.io/library/ubuntu:26.04@sha256:" + "f" * 64},
            "apt": {"nodejs": "22.22.1-1", "git": "1:2.53.0-1", "zip": "3.0"}}))
        out = br.versions(path)
        self.assertIn("| claude-code | 2.1.287 |", out)
        self.assertIn("| go | 1.27.2 |", out)
        self.assertIn("| node | 26.13.0 |", out)
        self.assertNotIn("nodejs (apt)", out)
        self.assertNotIn("SHA256", out)
        self.assertIn("20261008T000000Z", out)
        self.assertIn("sha256:ffffffffffff", out)
        self.assertIn("3 apt packages", out)

    def test_pins_shows_changes_only(self):
        old = self.write("# c\nGO_VERSION=1.27.1\nGO_SHA256_AMD64=" + "a" * 64 + "\nGONE=1\nSAME=x\n")
        new = self.write("GO_VERSION=1.27.2\nGO_SHA256_AMD64=" + "b" * 64 + "\nNEW=2\nSAME=x\n")
        out = br.pins(old, new)
        self.assertIn("| GO_VERSION | 1.27.1 | 1.27.2 |", out)
        self.assertIn("| GO_SHA256_AMD64 | aaaaaaaaaaaa... | bbbbbbbbbbbb... |", out)
        self.assertIn("| NEW | (none) | 2 |", out)
        self.assertIn("| GONE | 1 | (none) |", out)
        self.assertNotIn("SAME", out)

    def test_pins_without_changes_prints_nothing(self):
        a = self.write("A=1\n")
        self.assertEqual(br.pins(a, a), "")

    def test_pins_with_a_missing_old_file(self):
        out = br.pins(os.path.join(tempfile.gettempdir(), "does-not-exist.env"), self.write("A=1\n"))
        self.assertIn("| A | (none) | 1 |", out)

    def test_layers_largest_first(self):
        hist = "100\tRUN small\n3000000000\tRUN /bin/sh -c apt-get install |\n0\tENV X=1\n2500000\tCOPY rootfs/ /\n"
        out = br.layers(io.StringIO(hist), total=3002500100)
        self.assertIn("Image size: 2863.4 MiB", out)
        lines = [l for l in out.splitlines() if l.startswith("| ") and "MiB |" in l]
        self.assertTrue(lines[0].startswith("| 2861.0 MiB | RUN /bin/sh -c apt-get install \\| |"), lines[0])
        self.assertNotIn("ENV X=1", out)

    def test_layers_reads_human_sizes(self):
        # Podman prints "0 B" and "1.5 GB" even with --human=false; go-units sizes are decimal.
        out = br.layers(io.StringIO("1.5 GB\tRUN big\n0 B\tENV X=1\n300MB\tRUN mid\n"), total=1800000000)
        self.assertIn("| 1430.5 MiB | RUN big |", out)
        self.assertIn("| 286.1 MiB | RUN mid |", out)
        self.assertNotIn("ENV X=1", out)

    def test_layers_drop_the_build_arg_prefix(self):
        hist = ("5000000\t|4 APT_SNAPSHOT=2026 GID=1000 TARGETARCH=arm64 UID=1000 /bin/sh -c bash /tmp/install.sh\n"
                "4000000\t/bin/sh -c #(nop) COPY dir:abc in /\n")
        out = br.layers(io.StringIO(hist), total=9000000)
        self.assertIn("| 4.8 MiB | bash /tmp/install.sh |", out)
        self.assertIn("| 3.8 MiB | COPY dir:abc in / |", out)

    def test_sections_end_with_a_blank_line(self):
        self.assertTrue(br.layers(io.StringIO(""), total=0).endswith("\n\n"))

    def test_layers_truncates_long_commands(self):
        out = br.layers(io.StringIO("5000000\tRUN " + "x" * 500 + "\n"), total=5000000)
        self.assertLess(max(len(l) for l in out.splitlines()), 200)

    def test_tests_counts_each_file(self):
        log = self.write("# tests/10-base.sh\nok 1 - a\nok 2 - b\n1..2\n"
                         "# tests/80-mcp.sh\nok 1 - c\nnot ok 2 - sync works\n  # detail\n1..2\n")
        out = br.tests("Docker", log)
        self.assertIn("| tests/10-base.sh | 2 | 0 |", out)
        self.assertIn("| tests/80-mcp.sh | 1 | 1 |", out)
        self.assertIn("| Total | 3 | 1 |", out)
        self.assertIn("tests/80-mcp.sh: sync works", out)
        self.assertIn("Docker", out)

    def test_tests_counts_a_file_that_exited_non_zero(self):
        # tests/run.sh adds an unnumbered "not ok" line when a file exits non-zero
        # without printing a failing test of its own.
        log = self.write("# tests/10-base.sh\nok 1 - a\n"
                         "not ok - exited with status 2 without reporting a failing test\n"
                         "# tests/20-tools-apt.sh\nok 1 - b\n1..1\n")
        out = br.tests("Podman", log)
        self.assertIn("| tests/10-base.sh | 1 | 1 |", out)
        self.assertIn("| Total | 2 | 1 |", out)
        self.assertIn("tests/10-base.sh: exited with status 2 without reporting a failing test", out)


if __name__ == "__main__":
    unittest.main()
