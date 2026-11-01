"""Run the CPU check's runner setup with unavailable or stale APT indexes."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CpuCheckSetupTests(unittest.TestCase):
    def setup_check(self, failure=""):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        step = workflow.split("      - name: Agents and Node.js on a CPU without AVX2\n", 1)[1]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1]
                                 .split("      - name:", 1)[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stubs = {
                "sudo": '#!/bin/sh\nexec "$@"\n',
                "apt-get": '''#!/bin/sh
set -eu
echo "$*" >> "$CHECK_ROOT/calls"
case " $* " in
  *" update "*)
    [ "$CHECK_FAILURE" != update ] || exit 100
    touch "$CHECK_ROOT/indexes"
    ;;
  *" install "*)
    [ -f "$CHECK_ROOT/indexes" ] || { echo "stale index: package 404" >&2; exit 100; }
    [ "$CHECK_FAILURE" != install ] || exit 100
    ;;
  *) exit 2 ;;
esac
''',
                "docker": '#!/bin/sh\ntouch "$CHECK_ROOT/cpu-check"\n',
            }
            for name, body in stubs.items():
                path = root / name
                path.write_text(body)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"],
                       CHECK_ROOT=str(root), CHECK_FAILURE=failure,
                       IMAGE="fixture", GITHUB_STEP_SUMMARY=str(root / "summary"))
            result = subprocess.run(["bash", "-eo", "pipefail", "-c", script], env=env,
                                    capture_output=True, text=True, timeout=10)
            return result, (root / "calls").read_text(), (root / "cpu-check").exists()

    def test_refreshes_indexes_before_installing_qemu(self):
        result, calls, checked = self.setup_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("update --error-on=any", calls)
        self.assertIn("install -y -qq qemu-user", calls)
        self.assertTrue(checked)

    def test_failed_index_refresh_stops_before_install(self):
        result, calls, checked = self.setup_check("update")
        self.assertEqual(result.returncode, 100, result.stderr)
        self.assertNotIn("install", calls)
        self.assertFalse(checked)

    def test_failed_install_stops_before_cpu_check(self):
        result, calls, checked = self.setup_check("install")
        self.assertEqual(result.returncode, 100, result.stderr)
        self.assertIn("update --error-on=any", calls)
        self.assertFalse(checked)
