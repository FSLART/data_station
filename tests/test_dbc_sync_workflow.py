"""Protect PR validation boundaries."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def test_pull_requests_build_but_cannot_publish_releases():
    config = workflow('validate-dbc-arm64.yml')
    assert 'pull_request' in config['on']
    steps = config['jobs']['build-arm64']['steps']
    assert any('regenerate_dbcs.py' in s.get('run', '') for s in steps)
    releases = [s for s in steps if 'softprops/action-gh-release@' in s.get('uses', '')]
    assert not releases
    assert config['permissions']['contents'] == 'read'
