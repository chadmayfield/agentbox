"""Check the bump workflow's artifact transport, its Node.js install, the extras
failure job and the lint-unit extras checks, running their shell with stubs."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
BUMP = ROOT / ".github/workflows/bump.yml"
BUILD = ROOT / ".github/workflows/build.yml"
ACTION = ROOT / ".github/actions/bump-pr/action.yml"
UPLOAD = "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9  # v7.0.2"
DOWNLOAD = "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333  # v8.0.2"
EXTRAS = "rootfs/usr/local/share/agentainer/extras"
# A git without the user's global or system settings, such as commit signing.
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def job(path, name):
    """The text of one job under jobs:, up to the next job key."""
    text = path.read_text()
    m = re.search(r"^  %s:\n" % re.escape(name), text, re.M)
    if not m:
        raise AssertionError("no job %s in %s" % (name, path.name))
    rest = text[m.end():]
    end = re.search(r"^  [A-Za-z0-9_-]+:\s*$", rest, re.M)
    return rest[:end.start()] if end else rest


def steps(text):
    """The steps of a job or composite action, split on their list markers."""
    m = re.search(r"^( +)- ", text, re.M)
    if not m:
        return []
    marker = "\n" + m.group(1) + "- "
    parts = ("\n" + text[m.start():]).split(marker)[1:]
    # A comment line before a step marker belongs to the next step, not this one.
    out = []
    for part in parts:
        lines = (part + "\n").splitlines(keepends=True)
        while len(lines) > 1 and lines[-1].lstrip().startswith("#"):
            lines.pop()
        out.append("- " + "".join(lines))
    return out


def step(text, needle):
    found = [s for s in steps(text) if needle in s]
    if len(found) != 1:
        raise AssertionError("expected one step with %r, found %d" % (needle, len(found)))
    return found[0]


def run_body(step_text):
    lines = step_text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == "run: |":
            indent = len(line) - len(line.lstrip())
            body = []
            for rest in lines[i + 1:]:
                if rest.strip() and len(rest) - len(rest.lstrip()) <= indent:
                    break
                body.append(rest)
            return textwrap.dedent("".join(body))
    raise AssertionError("step has no run: | block")


def shell_flags(step_text):
    """The flags GitHub runs a step's script with on Linux.

    "shell: bash" runs bash --noprofile --norc -eo pipefail {0}; a step with no
    shell (and no defaults.run.shell, which these workflows do not set) runs
    bash -e {0} (GitHub docs, workflow-syntax, jobs.<job_id>.steps[*].shell).
    """
    if re.search(r"^ *(- )?shell: bash(\s|$)", step_text, re.M):
        return ["--noprofile", "--norc", "-eo", "pipefail"]
    return ["-e"]


def run_step(step_text, cwd, env, path_dirs=()):
    """Run a step's run: | script with the shell flags it declares."""
    full = dict(os.environ, **GIT_ENV)
    full.update(env)
    full["PATH"] = os.pathsep.join([str(d) for d in path_dirs] + [os.environ["PATH"]])
    return subprocess.run(["bash", *shell_flags(step_text), "-c", run_body(step_text)],
                          cwd=cwd, env=full, capture_output=True, text=True)


def stub(directory, name, body):
    p = Path(directory) / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(0o755)
    return p


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, env=dict(os.environ, **GIT_ENV), check=True,
                   capture_output=True, text=True)


class ResolveJobTests(unittest.TestCase):
    def setUp(self):
        self.job = job(BUMP, "resolve")

    def test_outputs_carry_no_patch(self):
        outputs = self.job.split("    outputs:\n", 1)[1].split("    steps:\n", 1)[0]
        keys = re.findall(r"^      ([A-Za-z0-9_-]+):", outputs, re.M)
        self.assertEqual(sorted(keys), ["app", "base", "changed"])
        self.assertNotIn("base64", BUMP.read_text())

    def test_node_installed_before_the_resolver(self):
        names = [s.split("\n", 1)[0] for s in steps(self.job)]
        node = [i for i, s in enumerate(steps(self.job)) if "build/fetch.sh" in s]
        resolver = [i for i, s in enumerate(steps(self.job)) if "scripts/bump_versions.py" in s]
        self.assertEqual(len(node), 1, names)
        self.assertEqual(len(resolver), 1, names)
        self.assertLess(node[0], resolver[0])

    def node_install(self, good_sum=True, version="9.8.7", digest=None):
        script = step(self.job, "build/fetch.sh")
        d = Path(tempfile.mkdtemp(prefix="cx-bump-node-"))
        self.addCleanup(shutil.rmtree, d)
        (d / "build").mkdir()
        shutil.copy(ROOT / "build/fetch.sh", d / "build/fetch.sh")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:xz") as tar:
            for name, text in (("node", "echo v9.8.7\n"), ("npm", "echo 1.0.0\n")):
                data = ("#!/bin/sh\n" + text).encode()
                info = tarfile.TarInfo("node-v9.8.7-linux-x64/bin/" + name)
                info.size, info.mode = len(data), 0o755
                tar.addfile(info, io.BytesIO(data))
        archive = d / "fake.tar.xz"
        archive.write_bytes(buf.getvalue())
        if digest is None:
            digest = hashlib.sha256(buf.getvalue()).hexdigest() if good_sum else "0" * 64
        (d / "versions.env").write_text("NODE_VERSION=%s\nNODE_SHA256_AMD64=%s\nNODE_SHA256_ARM64=%s\n"
                                        % (version, digest, "1" * 64))
        bins = d / "stubs"
        bins.mkdir()
        stub(bins, "curl", 'out=\nwhile [ $# -gt 1 ]; do\n  if [ "$1" = -o ]; then out=$2; shift; fi\n  shift\ndone\n'
             'echo "$1" >>"$CX_URLS"\ncp "$CX_ARCHIVE" "$out"\n')
        (d / "rt").mkdir()
        env = {"RUNNER_TEMP": str(d / "rt"), "GITHUB_PATH": str(d / "ghpath"),
               "CX_URLS": str(d / "urls"), "CX_ARCHIVE": str(archive)}
        return run_step(script, d, env, [bins]), d

    def test_node_from_fetch_sh_with_the_amd64_pin(self):
        result, d = self.node_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((d / "urls").read_text(),
                         "https://nodejs.org/dist/v9.8.7/node-v9.8.7-linux-x64.tar.xz\n")
        self.assertEqual((d / "ghpath").read_text(), str(d / "rt" / "node" / "bin") + "\n")
        self.assertTrue((d / "rt/node/bin/npm").is_file())

    def test_node_checksum_mismatch_fails_before_path(self):
        result, d = self.node_install(good_sum=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse((d / "ghpath").exists())

    def resolve(self, rc):
        script = step(self.job, "scripts/bump_versions.py")
        d = Path(tempfile.mkdtemp(prefix="cx-bump-resolve-"))
        self.addCleanup(shutil.rmtree, d)
        bins = d / "stubs"
        bins.mkdir()
        stub(bins, "python3", 'echo "$@" >"$CX_ARGS"\necho "X_VERSION: 1 -> 2"\nexit %d\n' % rc)
        (d / "rt").mkdir()
        result = run_step(script, d, {"RUNNER_TEMP": str(d / "rt"), "CX_ARGS": str(d / "args")}, [bins])
        return result, d

    def test_resolver_writes_failures_and_changes_to_runner_temp(self):
        result, d = self.resolve(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((d / "args").read_text(),
                         "scripts/bump_versions.py --failures %s\n" % (d / "rt/bump/failures.txt"))
        self.assertEqual((d / "rt/bump/changes.txt").read_text(), "X_VERSION: 1 -> 2\n")

    def test_missing_node_checksum_fails_before_download(self):
        result, d = self.node_install(digest="")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((d / "urls").exists())
        self.assertFalse((d / "ghpath").exists())

    def test_missing_node_version_fails_before_download(self):
        result, d = self.node_install(version="")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((d / "urls").exists())
        self.assertFalse((d / "ghpath").exists())

    def test_resolve_step_declares_bash(self):
        # Without it GitHub runs bash -e with no pipefail, and tee hides a failed resolver.
        self.assertIn("shell: bash", step(self.job, "scripts/bump_versions.py"))

    def test_timeout(self):
        self.assertIn("    timeout-minutes: 30\n", self.job)

    def test_resolver_failure_fails_the_step(self):
        result, _ = self.resolve(1)
        self.assertNotEqual(result.returncode, 0)

    def diff(self, change):
        script = step(self.job, "id: diff")
        d = Path(tempfile.mkdtemp(prefix="cx-bump-diff-"))
        self.addCleanup(shutil.rmtree, d)
        repo = d / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        (repo / "versions.env").write_text("X_VERSION=1\n")
        git(repo, "add", "versions.env")
        git(repo, "commit", "-qm", "base")
        if change:
            (repo / "versions.env").write_text("X_VERSION=2\n")
        (d / "rt" / "bump").mkdir(parents=True)
        out = d / "output"
        result = run_step(script, repo, {"RUNNER_TEMP": str(d / "rt"), "GITHUB_OUTPUT": str(out),
                                     "HAS_APP_KEY": "false", "HAS_APP_ID": "false"})
        return result, d, out.read_text() if out.exists() else ""

    def test_changed_pins_go_to_a_patch_file(self):
        result, d, out = self.diff(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        keys = sorted(line.split("=", 1)[0] for line in out.splitlines())
        self.assertEqual(keys, ["app", "base", "changed"])
        self.assertIn("changed=true\n", out)
        clone = d / "clone"
        git(d, "clone", "-q", str(d / "repo"), str(clone))
        git(clone, "apply", "--index", str(d / "rt/bump/bump.patch"))
        self.assertEqual((clone / "versions.env").read_text(), "X_VERSION=2\n")

    def test_no_change_writes_no_patch(self):
        result, d, out = self.diff(False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("changed=false\n", out)
        self.assertFalse((d / "rt/bump/bump.patch").exists())

    def test_upload_carries_the_bump_directory(self):
        s = step(self.job, "upload-artifact")
        self.assertIn("uses: " + UPLOAD + "\n", s)
        self.assertIn("name: bump-patch\n", s)
        self.assertIn("path: ${{ runner.temp }}/bump/\n", s)
        self.assertIn("retention-days: 1\n", s)
        self.assertIn("if: always() && steps.resolve.outcome != 'skipped'\n", s)
        self.assertIn("if-no-files-found: error\n", s)
        self.assertRegex(s, r"\n +overwrite: true( +#[^\n]*)?\n")


class PullRequestJobTests(unittest.TestCase):
    def test_pr_jobs_download_after_checkout_and_pass_files(self):
        for name in ("pr-app", "pr-token"):
            with self.subTest(job=name):
                text = job(BUMP, name)
                all_steps = steps(text)
                checkout = [i for i, s in enumerate(all_steps) if "actions/checkout@" in s]
                download = [i for i, s in enumerate(all_steps) if "download-artifact" in s]
                action = [i for i, s in enumerate(all_steps) if "./.github/actions/bump-pr" in s]
                self.assertEqual(len(download), 1)
                self.assertLess(checkout[0], download[0])
                self.assertLess(download[0], action[0])
                d = all_steps[download[0]]
                self.assertIn("uses: " + DOWNLOAD + "\n", d)
                self.assertIn("name: bump-patch\n", d)
                self.assertIn("path: ${{ runner.temp }}/bump\n", d)
                a = all_steps[action[0]]
                self.assertIn("patch-file: ${{ runner.temp }}/bump/bump.patch\n", a)
                self.assertIn("changes-file: ${{ runner.temp }}/bump/changes.txt\n", a)
                self.assertNotRegex(a, r"\n +(patch|changes):")
                self.assertNotIn("needs.resolve.outputs.patch", text)

    def test_permissions_unchanged(self):
        self.assertIn("    permissions:\n      contents: read\n", job(BUMP, "resolve"))
        self.assertIn("    permissions:\n      contents: read\n", job(BUMP, "pr-app"))
        self.assertIn("    permissions:\n      contents: write\n      pull-requests: write\n",
                      job(BUMP, "pr-token"))


class BumpPrActionTests(unittest.TestCase):
    def test_inputs_are_file_paths(self):
        text = ACTION.read_text()
        inputs = text.split("inputs:\n", 1)[1].split("runs:\n", 1)[0]
        keys = re.findall(r"^  ([A-Za-z0-9_-]+):", inputs, re.M)
        self.assertEqual(sorted(keys), ["app-slug", "changes-file", "patch-file", "token"])
        self.assertNotRegex(text, r"\n +PATCH:")
        self.assertNotIn("base64", text)

    def run_action(self, mutate, changes="X_VERSION: 1.0.0 -> 1.1.0\n", report=None, worktree=None, extra=None):
        """Run the action's shell on a clone of a scratch repository.

        mutate(seed) changes the seed checkout; the staged result, with rename
        detection, is the patch. report replaces scripts/build_report.py in the
        base commit, and worktree(work) runs on the clone before the action.
        Returns the result, the bump branches on the remote and the temp dir.
        """
        script = step(ACTION.read_text(), "shell: bash")
        d = Path(tempfile.mkdtemp(prefix="cx-bump-action-"))
        self.addCleanup(shutil.rmtree, d)
        remote = d / "remote.git"
        git(d, "init", "-q", "--bare", str(remote))
        seed = d / "seed"
        git(d, "clone", "-q", str(remote), str(seed))
        files = {"versions.env": "X_VERSION=1.0.0\n",
                 "deploy/kubernetes/containerssh/deployment.yaml": "image: a\n",
                 EXTRAS + "/kandev/package.json": "{}\n",
                 EXTRAS + "/kandev/package-lock.json": "{}\n",
                 EXTRAS + "/kandev/sub/package.json": "{}\n"}
        files.update(extra or {})
        for rel, text in files.items():
            (seed / rel).parent.mkdir(parents=True, exist_ok=True)
            (seed / rel).write_text(text)
        (seed / "scripts").mkdir()
        if report is None:
            shutil.copy(ROOT / "scripts/build_report.py", seed / "scripts/build_report.py")
        else:
            (seed / "scripts/build_report.py").write_text(report)
        git(seed, "add", ".")
        git(seed, "commit", "-qm", "base")
        git(seed, "push", "-q", "origin", "HEAD:refs/heads/develop")
        mutate(seed)
        git(seed, "add", "-A")
        rt = d / "rt"
        (rt / "bump").mkdir(parents=True)
        (rt / "bump/bump.patch").write_bytes(subprocess.run(
            ["git", "diff", "--cached", "--binary", "-M"], cwd=seed, env=dict(os.environ, **GIT_ENV),
            capture_output=True, check=True).stdout)
        (rt / "bump/changes.txt").write_text(changes)
        work = d / "work"
        git(d, "clone", "-q", "-b", "develop", str(remote), str(work))
        if worktree:
            worktree(work)
        bins = d / "stubs"
        bins.mkdir()
        stub(bins, "gh", 'case "$1" in\npr) echo "$@" >"$CX_GH"; cp "$RUNNER_TEMP/body.md" "$CX_BODY" ;;\n'
             '*) echo 1 ;;\nesac\n')
        env = {"GH_TOKEN": "x", "APP_SLUG": "", "RUN": "7", "RUNNER_TEMP": str(rt),
               "PATCH_FILE": str(rt / "bump/bump.patch"), "CHANGES_FILE": str(rt / "bump/changes.txt"),
               "CX_GH": str(d / "gh-args"), "CX_BODY": str(d / "body.md")}
        result = run_step(script, work, env, [bins])
        branches = subprocess.run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/bump/"],
                                  cwd=remote, capture_output=True, text=True, check=True).stdout.split()
        return result, branches, d

    def show(self, d, ref, rel):
        return subprocess.run(["git", "show", "%s:%s" % (ref, rel)], cwd=d / "remote.git",
                              capture_output=True, text=True, check=True).stdout

    def test_shell_applies_the_patch_file(self):
        def mutate(seed):
            (seed / "versions.env").write_text("X_VERSION=1.1.0\n")
            (seed / "deploy/kubernetes/containerssh/deployment.yaml").write_text("image: b\n")
            (seed / EXTRAS / "kandev/package.json").write_text('{"v": 2}\n')
            (seed / EXTRAS / "kandev/package-lock.json").write_text('{"v": 2}\n')
        result, branches, d = self.run_action(mutate)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(branches), 1)
        self.assertRegex(branches[0], r"^bump/\d{4}-\d{2}-\d{2}-7$")
        self.assertEqual(self.show(d, branches[0], "versions.env"), "X_VERSION=1.1.0\n")
        self.assertEqual(self.show(d, branches[0], EXTRAS + "/kandev/package-lock.json"), '{"v": 2}\n')
        self.assertEqual(self.show(d, branches[0], "deploy/kubernetes/containerssh/deployment.yaml"), "image: b\n")
        self.assertIn("X_VERSION: 1.0.0 -> 1.1.0", (d / "body.md").read_text())
        self.assertIn("--base develop", (d / "gh-args").read_text())

    def assert_refused(self, mutate, needle):
        result, branches, d = self.run_action(mutate)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("refusing the patch", result.stdout + result.stderr)
        self.assertIn(needle, result.stdout + result.stderr)
        self.assertEqual(branches, [])
        self.assertFalse((d / "gh-args").exists())

    def test_patch_outside_the_allowlist_is_refused(self):
        def mutate(seed):
            (seed / "versions.env").write_text("X_VERSION=1.1.0\n")
            (seed / "scripts/build_report.py").write_text("print('x')\n")
        self.assert_refused(mutate, "scripts/build_report.py")

    def test_nested_catalog_path_is_refused(self):
        def mutate(seed):
            (seed / EXTRAS / "kandev/sub/package.json").write_text('{"v": 2}\n')
        self.assert_refused(mutate, EXTRAS + "/kandev/sub/package.json")

    def test_path_with_a_trailing_tab_is_refused(self):
        def mutate(seed):
            (seed / "versions.env\t").write_text("X_VERSION=1.1.0\n")
        result, branches, d = self.run_action(mutate, extra={"versions.env\t": "X_VERSION=1.0.0\n"})
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("refusing the patch", result.stdout)
        self.assertEqual(branches, [])
        self.assertFalse((d / "gh-args").exists())

    def test_rename_is_refused(self):
        def mutate(seed):
            (seed / EXTRAS / "kandev2").mkdir()
            git(seed, "mv", EXTRAS + "/kandev/package.json", EXTRAS + "/kandev2/package.json")
        self.assert_refused(mutate, "rename")

    def test_deletion_is_refused(self):
        def mutate(seed):
            (seed / EXTRAS / "kandev/package-lock.json").unlink()
        self.assert_refused(mutate, "delete")

    def test_mode_change_is_refused(self):
        def mutate(seed):
            (seed / "versions.env").chmod(0o755)
        self.assert_refused(mutate, "mode change")

    def test_binary_patch_is_refused(self):
        def mutate(seed):
            (seed / "versions.env").write_bytes(b"X_VERSION=1.1.0\n\x00\x01\x02\n")
        self.assert_refused(mutate, "binary")

    def test_build_report_runs_from_the_unpatched_commit(self):
        def mutate(seed):
            (seed / "versions.env").write_text("X_VERSION=1.1.0\n")
        def worktree(work):
            (work / "scripts/build_report.py").write_text("print('WORKTREE REPORT')\n")
        result, branches, d = self.run_action(mutate, report="print('BASE REPORT')\n", worktree=worktree)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        body = (d / "body.md").read_text()
        self.assertIn("BASE REPORT", body)
        self.assertNotIn("WORKTREE REPORT", body)

    def test_backticks_in_changes_cannot_close_the_fence(self):
        def mutate(seed):
            (seed / "versions.env").write_text("X_VERSION=1.1.0\n")
        line = "X_VERSION: npm said ```` and ``` here"
        result, _, d = self.run_action(mutate, changes=line + "\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        assert_fenced(self, (d / "body.md").read_text(), line)


def assert_fenced(test, text, line):
    """line sits inside one fenced block whose fence is longer than any backtick run in it."""
    lines = text.splitlines()
    fences = [i for i, x in enumerate(lines) if re.fullmatch(r"`{3,}", x)]
    test.assertEqual(len(fences), 2, text)
    a, b = fences
    test.assertEqual(lines[a], lines[b])
    test.assertIn(line, lines[a + 1:b])
    longest = max([len(r) for r in re.findall(r"`+", "\n".join(lines[a + 1:b]))] + [0])
    test.assertGreater(len(lines[a]), max(longest, 2))


class ExtrasFailuresJobTests(unittest.TestCase):
    def setUp(self):
        self.job = job(BUMP, "extras-failures")

    def test_runs_after_every_job(self):
        self.assertIn("    needs: [resolve, pr-app, pr-token]\n", self.job)
        self.assertIn("    if: always()\n", self.job)
        self.assertIn("    permissions:\n      contents: read\n", self.job)
        s = step(self.job, "download-artifact")
        self.assertIn("uses: " + DOWNLOAD + "\n", s)
        self.assertIn("name: bump-patch\n", s)
        self.assertIn("continue-on-error: true\n", s)

    def check(self, content, resolve="success"):
        script = step(self.job, "FAILURES")
        d = Path(tempfile.mkdtemp(prefix="cx-bump-failures-"))
        self.addCleanup(shutil.rmtree, d)
        failures = d / "failures.txt"
        if content is not None:
            failures.write_text(content)
        summary = d / "summary"
        result = run_step(script, d, {"FAILURES": str(failures), "RESOLVE": resolve,
                                  "GITHUB_STEP_SUMMARY": str(summary)})
        return result, summary.read_text() if summary.exists() else ""

    def test_empty_file_passes(self):
        result, _ = self.check("")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_failures_fail_and_print_each_line(self):
        result, summary = self.check("extras kandev: bad signature\nextras rea: new install script\n")
        self.assertNotEqual(result.returncode, 0)
        for line in ("extras kandev: bad signature", "extras rea: new install script"):
            self.assertIn(line, result.stdout)
            self.assertIn(line, summary)

    def test_backticks_in_failures_cannot_close_the_fence(self):
        line = "extras kandev: npm said ``` and ```` here"
        result, summary = self.check(line + "\n")
        self.assertNotEqual(result.returncode, 0)
        assert_fenced(self, summary, line)

    def test_missing_file_after_a_successful_resolve_fails(self):
        result, _ = self.check(None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stdout)

    def test_missing_file_after_a_failed_resolve_defers_to_resolve(self):
        result, _ = self.check(None, resolve="failure")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class LintUnitTests(unittest.TestCase):
    def setUp(self):
        self.job = job(BUILD, "lint-unit")

    def test_runs_the_extras_catalog_tests(self):
        self.assertRegex(step(self.job, "test-extras-catalog.sh"),
                         r"run: sh tests/host/test-extras-catalog\.sh\n")

    def scan(self, with_dir, docker_rc=0, report=None):
        script = step(self.job, "trivy")
        d = Path(tempfile.mkdtemp(prefix="cx-extras-scan-"))
        self.addCleanup(shutil.rmtree, d)
        (d / "versions.env").write_text("TRIVY_SCANNER_IMAGE=docker.io/example/trivy:1@sha256:%s\n" % ("a" * 64))
        if with_dir:
            (d / EXTRAS / "kandev").mkdir(parents=True)
        bins = d / "stubs"
        bins.mkdir()
        shutil.copytree(ROOT / "scripts", d / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        # Writes a one-finding trivy JSON report to the directory mounted at /report.
        stub(bins, "docker", 'echo "$@" >>"$CX_DOCKER"\n[ "$CX_RC" = 0 ] || exit "$CX_RC"\n'
             'for a in "$@"; do case "$a" in *:/report) out=${a%:/report} ;; esac; done\n'
             'printf %s "$CX_JSON" >"$out/extras.json"\n')
        report = report if report is not None else json.dumps({"Results": [{"Target": "kandev/package-lock.json", "Type": "npm", "Vulnerabilities": [
            {"VulnerabilityID": "CVE-2026-0001", "PkgName": "left-pad", "InstalledVersion": "1.0.0",
             "FixedVersion": "1.0.1", "Severity": "CRITICAL"}]}]})
        summary = d / "summary"
        (d / "rt").mkdir()
        result = run_step(script, d, {"GITHUB_STEP_SUMMARY": str(summary), "CX_DOCKER": str(d / "docker"),
                                      "RUNNER_TEMP": str(d / "rt"), "CX_RC": str(docker_rc),
                                      "CX_JSON": report}, [bins])
        docker = (d / "docker").read_text() if (d / "docker").exists() else None
        return result, docker, summary.read_text() if summary.exists() else "", d

    def test_scan_is_report_only_with_the_pinned_scanner(self):
        result, docker, summary, d = self.scan(True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(docker.splitlines()), 1)
        args = docker.split()
        self.assertIn("docker.io/example/trivy:1@sha256:" + "a" * 64, args)
        image = args.index("docker.io/example/trivy:1@sha256:" + "a" * 64)
        rest = " ".join(args[image + 1:])
        self.assertTrue(rest.startswith("fs "), rest)
        self.assertIn("--scanners vuln", rest)
        self.assertIn("--exit-code 0", rest)
        self.assertIn("--format json", rest)
        self.assertIn("%s:/scan:ro" % (d / EXTRAS), docker)
        # vuln_summary.py's table and critical list, not the full JSON.
        self.assertIn("| CRITICAL | 1 (1 fixable) |", summary)
        self.assertIn("CVE-2026-0001", summary)
        self.assertNotIn('"Results"', summary)

    def test_scanner_failure_is_reported_not_fatal(self):
        result, docker, summary, _ = self.scan(True, docker_rc=125)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNotNone(docker)
        self.assertIn("::warning::Extras lockfile scan did not run (scanner or database download failed).",
                      result.stdout)
        self.assertIn("Extras lockfile scan did not run.", summary)

    def test_unreadable_report_is_reported_not_fatal(self):
        result, docker, summary, _ = self.scan(True, report="{not json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNotNone(docker)
        self.assertIn("::warning::Extras lockfile scan report could not be read.", result.stdout)
        self.assertIn("Extras lockfile scan report could not be read.", summary)

    def test_missing_catalog_skips_the_scan(self):
        result, docker, summary, _ = self.scan(False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNone(docker)
        self.assertIn("No extras catalog", summary)


if __name__ == "__main__":
    unittest.main()
