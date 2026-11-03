"""Offline startup regression tests. Never invokes Hermes or uses production data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(os.environ.get("STARTUP_SCRIPT", "start.sh")).read_text()


class StartupTests(unittest.TestCase):
    def run_start(self, failure="", profile=True, key=True, initial="KEEP=value\n", repeats=1):
        with tempfile.TemporaryDirectory(prefix="hermes-startup-test-") as root:
            root = Path(root)
            home = root / "data" / "tdautomate"
            if profile:
                home.mkdir(parents=True)
                (home / ".env").write_text(initial)
            binary = root / "bin"
            binary.mkdir()
            log = root / "commands.jsonl"
            mock = binary / "hermes"
            mock.write_text("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
home = os.environ.get('HERMES_HOME')
with open(os.environ['MOCK_LOG'], 'a') as f:
    f.write(json.dumps({'args': args, 'home': home}) + '\\n')
failure = os.environ.get('MOCK_FAILURE', '')
fail = (failure == 'default-gateway' and args == ['gateway', 'run'] and not home)
fail |= (failure == 'td-gateway' and args == ['gateway', 'run'] and bool(home))
fail |= (bool(failure) and any(failure == arg for arg in args))
sys.exit(37 if fail else 0)
""")
            mock.chmod(0o755)
            for command in ("touch", "awk", "mv"):
                real = shutil.which(command)
                wrapper = binary / command
                wrapper.write_text(f'#!/bin/sh\n[ "$MOCK_FAILURE" = "{command}" ] && exit 37\nexec "{real}" "$@"\n')
                wrapper.chmod(0o755)
            sleep = binary / "sleep"
            sleep.write_text("#!/bin/sh\nexit 0\n")
            sleep.chmod(0o755)
            script = root / "start.test.sh"
            script.write_text(SOURCE.replace("/opt/data/agent/tdautomate", str(home)))
            env = {"PATH": str(binary) + ":" + os.environ["PATH"], "MOCK_LOG": str(log), "MOCK_FAILURE": failure}
            if key:
                env["TD_AUTOMATE_API_SERVER_KEY"] = "test-only-dummy-not-a-secret"
            result = None
            for _ in range(repeats):
                result = subprocess.run(["bash", str(script)], env=env, text=True, capture_output=True, timeout=10)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            data = (home / ".env").read_text() if (home / ".env").is_file() else ""
            return result, calls, data

    def td_started(self, calls):
        return any(c["args"] == ["gateway", "run"] and c["home"] for c in calls)

    def test_success_preserves_default_and_scopes_configuration(self):
        result, calls, data = self.run_start()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls[0], {"args": ["gateway", "run"], "home": None})
        self.assertEqual([c["args"][0] for c in calls], ["gateway", "config", "config", "gateway"])
        self.assertTrue(all(c["home"] for c in calls[1:]))
        self.assertIn("KEEP=value\n", data)
        self.assertIn("API_SERVER_PORT=8650\n", data)

    def test_configuration_failures_do_not_launch_td_gateway(self):
        for failure in ("agent.disabled_toolsets", "approvals.mode"):
            with self.subTest(failure=failure):
                result, calls, _ = self.run_start(failure=failure)
                self.assertEqual(result.returncode, 0)
                self.assertFalse(self.td_started(calls))
                self.assertIn("preserving the default gateway", result.stdout)

    def test_environment_write_failures_do_not_launch_td_gateway(self):
        for failure in ("touch", "awk", "mv"):
            with self.subTest(failure=failure):
                result, calls, data = self.run_start(failure=failure)
                self.assertEqual(result.returncode, 0)
                self.assertFalse(self.td_started(calls))
                self.assertEqual(data, "KEEP=value\n")
                self.assertIn("preserving the default gateway", result.stdout)

    def test_missing_profile_or_key_leaves_default_only(self):
        for profile, key in ((False, True), (True, False)):
            with self.subTest(profile=profile, key=key):
                result, calls, _ = self.run_start(profile=profile, key=key)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(len(calls), 1)
                self.assertFalse(self.td_started(calls))

    def test_default_gateway_failure_is_not_hidden(self):
        result, calls, _ = self.run_start(failure="default-gateway")
        self.assertEqual(result.returncode, 37)
        self.assertEqual(len(calls), 1)

    def test_td_gateway_failure_preserves_default(self):
        result, calls, _ = self.run_start(failure="td-gateway")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls[0]["home"], None)
        self.assertIn("preserving the default gateway", result.stdout)

    def test_repeated_startup_deduplicates_owned_keys(self):
        _, _, data = self.run_start(initial="KEEP=value\nAPI_SERVER_PORT=old\nAPI_SERVER_PORT=duplicate\n", repeats=2)
        self.assertEqual(data.count("API_SERVER_PORT="), 1)
        self.assertIn("API_SERVER_PORT=8650\n", data)
        self.assertIn("KEEP=value\n", data)


if __name__ == "__main__":
    unittest.main()
