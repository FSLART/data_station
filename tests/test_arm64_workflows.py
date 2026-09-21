import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class Arm64WorkflowTests(unittest.TestCase):
    def test_cached_build_is_automatic_and_can_be_run_manually(self):
        workflow = (WORKFLOWS / "build-arm64.yml").read_text()

        self.assertIn("name: Build ARM64 (Cached)", workflow)
        self.assertIn("push:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("actions/cache/restore@v4", workflow)
        self.assertIn("actions/cache/save@v4", workflow)
        self.assertIn("softprops/action-gh-release@v3", workflow)

    def test_clean_build_is_manual_uncached_and_does_not_replace_release(self):
        workflow = (WORKFLOWS / "build-arm64-clean.yml").read_text()

        self.assertIn("name: Build ARM64 (Clean)", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertNotIn("actions/cache/", workflow)
        self.assertNotIn("softprops/action-gh-release", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("lart-dashboard-arm64-clean", workflow)


if __name__ == "__main__":
    unittest.main()
