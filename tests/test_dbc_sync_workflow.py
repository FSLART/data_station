"""Protect publication ordering and PR validation boundaries."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def test_sync_builds_before_publishing_and_pins_interface_commit():
    config = workflow('regenerate-dbcs.yml')
    update = config['jobs']['sync-dbc']
    publication_job = config['jobs']['publish']
    assert publication_job['needs'] == 'sync-dbc'
    assert publication_job['if'] == "needs.sync-dbc.outputs.changed == 'true'"
    steps = publication_job['steps']
    names = [step['name'] for step in steps]
    update_names = [step['name'] for step in update['steps']]
    assert update_names.index('Adapt DBC consumers with OpenRouter') < update_names.index('Test DBC outputs')
    assert update_names.index('Build dashboard UI') < update_names.index('Package tested changes')
    assert update_names.index('Package tested changes') < update_names.index('Upload tested changes')
    assert names.index('Pin published interfaces') < names.index('Publish dashboard PR')
    source = next(s for s in update['steps'] if s['name'] == 'Checkout DBC source')
    assert source['with']['repository'] == 'FSLART/T26_DBC'
    assert source['with']['path'] == 'build/dbc-source'
    interfaces = next(s for s in steps if s['name'] == 'Publish interface PR')
    assert 'publish-dbc-pr.sh build/interface-publish FSLART/lart_msgs main' in interfaces['run']
    publication = next(s for s in steps if s['name'] == 'Checkout interface publication repository')
    assert publication['with']['repository'] == 'FSLART/lart_msgs'
    assert publication['with']['ref'] == '${{ needs.sync-dbc.outputs.interface_sha }}'
    assert publication['with']['path'] == 'build/interface-publish'
    assert names.index('Apply tested changes') < names.index('Publish interface PR')
    assert 'git push' not in str(update)


def test_openrouter_is_free_only_gated_and_has_no_publication_credentials():
    config = workflow('regenerate-dbcs.yml')
    update = config['jobs']['sync-dbc']
    assert config['permissions']['contents'] == 'read'
    assert 'pull_request' not in config['on']
    codex = next(s for s in update['steps'] if s.get('uses', '').startswith('openai/codex-action@'))
    assert codex['if'] == "steps.changes.outputs.changed == 'true'"
    assert codex['with']['openai-api-key'] == '${{ secrets.OPENROUTER_API_KEY }}'
    assert codex['with']['responses-api-endpoint'] == 'https://openrouter.ai/api/v1/responses'
    assert codex['with']['model'] == 'openrouter/free'
    assert codex['with']['prompt-file'] == '.github/prompts/dbc-update.md'
    assert (ROOT / codex['with']['prompt-file']).is_file()
    assert codex['with']['permission-profile'] == ':workspace'
    assert codex['with']['safety-strategy'] == 'drop-sudo'
    assert codex['with']['output-schema']
    names = [s['name'] for s in update['steps']]
    assert names.index('Set up ROS2 build') < names.index('Adapt DBC consumers with OpenRouter')
    assert names.index('Require completed adaptation') < names.index('Test DBC outputs')
    assert 'DBC_SYNC_TOKEN' not in str(update)
    assert 'secrets.OPENAI_API_KEY' not in str(config)
    assert 'secrets.ANTHROPIC_API_KEY' not in str(config)
    assert all(s.get('with', {}).get('persist-credentials') == 'false'
               for s in update['steps'] if s.get('uses', '').startswith('actions/checkout@'))


def test_publication_uses_tested_snapshot_and_includes_handwritten_changes():
    config = workflow('regenerate-dbcs.yml')
    publish = config['jobs']['publish']['steps']
    checkout = next(s for s in publish if s['name'] == 'Checkout destination repository')
    assert checkout['with']['ref'] == '${{ needs.sync-dbc.outputs.destination_sha }}'
    assert not any('sudo' in s.get('run', '') or 'pip' in s.get('run', '') for s in publish)
    parent = next(s for s in publish if s['name'] == 'Publish dashboard PR')
    assert config['jobs']['publish']['env']['GH_TOKEN'] == '${{ secrets.DBC_SYNC_TOKEN }}'
    assert parent['env']['DESTINATION_REPOSITORY'] == '${{ github.repository }}'
    package = next(s for s in config['jobs']['sync-dbc']['steps'] if s['name'] == 'Package tested changes')
    for path in ('src/lart_bringup', 'src/sim', 'src/led_controller', 'src/input_handler', 'foxglove_extensions', 'tests', 'scripts', 'docs'):
        assert path in package['run']
    assert not (ROOT / '.github/workflows/fetch-dbcs.yml').exists()


def test_pull_requests_build_but_cannot_publish_releases():
    config = workflow('validate-dbc-arm64.yml')
    assert 'pull_request' in config['on']
    steps = config['jobs']['build-arm64']['steps']
    assert any('regenerate_dbcs.py' in s.get('run', '') for s in steps)
    releases = [s for s in steps if 'softprops/action-gh-release@' in s.get('uses', '')]
    assert not releases
    assert config['permissions']['contents'] == 'read'
