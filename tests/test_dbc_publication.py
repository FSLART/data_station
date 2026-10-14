"""Publication keeps the tested tree even when the target branch advances."""
import os
from pathlib import Path
import subprocess


PUBLISH = Path(__file__).resolve().parents[1] / '.github/scripts/publish-dbc-pr.sh'


def git(directory, *args):
    return subprocess.check_output(['git', '-C', str(directory), *args], text=True).strip()


def test_publish_preserves_tested_tree_and_skips_empty_updates(tmp_path):
    remote = tmp_path / 'remote.git'
    git(tmp_path, 'init', '--bare', '--initial-branch=master', str(remote))
    checkout = tmp_path / 'checkout'
    git(tmp_path, 'clone', str(remote), str(checkout))
    git(checkout, 'config', 'user.name', 'DBC test')
    git(checkout, 'config', 'user.email', 'dbc-test@example.invalid')
    (checkout / 'consumer.py').write_text('old consumer\n')
    git(checkout, 'add', '.')
    git(checkout, 'commit', '-m', 'baseline')
    git(checkout, 'push', 'origin', 'master')
    baseline = git(checkout, 'rev-parse', 'HEAD')

    (checkout / 'consumer.py').write_text('adapted consumer\n')
    (checkout / 'New.msg').write_text('float64 temperature\n')
    git(checkout, 'add', '.')
    tested_tree = git(checkout, 'write-tree')

    # Advance the destination after tests/preflight, reproducing the PR helper's
    # former race without network access or any changes to the real repository.
    other = tmp_path / 'other'
    git(tmp_path, 'clone', str(remote), str(other))
    (other / 'unrelated.txt').write_text('new baseline content\n')
    git(other, 'add', '.')
    git(other, '-c', 'user.name=DBC test', '-c', 'user.email=dbc-test@example.invalid',
        'commit', '-m', 'advance base')
    git(other, 'push', 'origin', 'master')

    # Only the external PR API is replaced; commit/tree/lease/push operations
    # exercise real Git against the bare remote.
    binary = tmp_path / 'bin'
    binary.mkdir()
    gh = binary / 'gh'
    gh.write_text('#!/bin/sh\ncase "$1 $2" in\n'
                  '"pr list") exit 0 ;;\n'
                  '"pr create") echo https://example.invalid/pull/1 ;;\n'
                  '*) exit 99 ;;\nesac\n')
    gh.chmod(0o755)
    body = tmp_path / 'body.md'
    body.write_text('Tested DBC update\n')
    output = tmp_path / 'output'
    env = dict(os.environ, PATH=f'{binary}:{os.environ["PATH"]}', GITHUB_OUTPUT=str(output))
    command = ['bash', str(PUBLISH), str(checkout), 'owner/repository', 'master', 'DBC update', str(body)]
    subprocess.run(command, env=env, check=True, capture_output=True, text=True)
    published = git(remote, 'rev-parse', 'refs/heads/automation/dbc-regeneration')
    assert git(remote, 'rev-parse', f'{published}^{{tree}}') == tested_tree
    assert git(remote, 'rev-parse', f'{published}^') == baseline
    assert git(remote, 'rev-parse', 'master') != baseline
    assert f'sha={published}' in output.read_text()
    assert 'url=https://example.invalid/pull/1' in output.read_text()

    output.write_text('')
    subprocess.run(command, env=env, check=True, capture_output=True, text=True)
    assert output.read_text() == f'sha={published}\n'
    assert git(remote, 'rev-parse', 'refs/heads/automation/dbc-regeneration') == published
