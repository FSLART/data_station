import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class Arm64WorkflowTests(unittest.TestCase):
    def release_steps(self, filename):
        workflow = yaml.load(
            (WORKFLOWS / filename).read_text(), Loader=yaml.BaseLoader
        )
        jobs = workflow["jobs"].values()
        steps = [step for job in jobs for step in job["steps"]]
        return {
            step["name"]: step
            for step in steps
            if step.get("uses", "").startswith("softprops/action-gh-release@")
        }

    def test_normal_build_preserves_each_version_and_updates_latest(self):
        releases = self.release_steps("build-arm64.yml")

        self.assertEqual(
            releases["Publish versioned release"]["with"]["tag_name"],
            "arm64-${{ github.sha }}",
        )
        self.assertEqual(
            releases["Update latest release"]["with"]["tag_name"],
            "latest-arm64",
        )

    def test_only_normal_build_and_tagged_release_publish(self):
        # DBC validation/sync must not introduce another publisher.
        publishers = sorted(path.name for path in WORKFLOWS.glob('*.yml')
                            if self.release_steps(path.name))
        self.assertEqual(publishers, ['build-arm64.yml', 'release.yml'])

    def test_pi_builds_exclude_the_simulator(self):
        for filename in ("build-arm64.yml", "release.yml"):
            workflow = yaml.load((WORKFLOWS / filename).read_text(), Loader=yaml.BaseLoader)
            commands = " ".join(step.get("run", "") for job in workflow["jobs"].values()
                                for step in job["steps"])
            self.assertIn("--packages-up-to data_station_runtime input_handler led_controller --", commands)
            self.assertNotIn(" sim ", commands)

    def test_tagged_release_is_a_pi_bundle(self):
        workflow = yaml.load((WORKFLOWS / "release.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow["jobs"]["build"]["runs-on"], "ubuntu-24.04-arm")
        self.assertEqual(
            self.release_steps("release.yml")["Publish release"]["with"]["tag_name"],
            "${{ inputs.tag || github.ref_name }}",
        )


if __name__ == "__main__":
    unittest.main()
