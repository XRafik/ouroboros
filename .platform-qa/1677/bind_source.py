#!/usr/bin/env python3
"""Offline binding only. Run deliberately AFTER reading the final candidate diff.
No Ouroboros imports, commands, downloads or source edits. Never auto-run in CI.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

CONSUMED = (
    'ouroboros/claudexor_runtime_pin.json', 'ouroboros/claudexor_daemon.py',
    'ouroboros/gateways/claudexor.py', 'ouroboros/gateways/claudexor_maintenance.py',
    'ouroboros/platform_layer.py', 'ouroboros/config.py',
    'ouroboros/process_custody.py', 'ouroboros/process_scope.py',
    'scripts/safe_test.py', 'ouroboros/test_environment.py', 'ouroboros/safe_test_supervisor.py',
    'pyproject.toml', 'uv.lock',
)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def bind(source, candidate, expected_hash, output):
    source, candidate, output = Path(source).resolve(), Path(candidate), Path(output)
    if digest(candidate) != expected_hash:
        raise ValueError('candidate manifest hash mismatch')
    manifest = json.loads(candidate.read_text(encoding='utf-8'))
    files = {}
    names = []
    for row in manifest['files']:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts or not (source / relative).resolve().is_relative_to(source):
            raise ValueError('candidate file escapes source')
        if row['path'] in files:
            raise ValueError('duplicate candidate file')
        actual = digest(source / relative)
        if actual != row['sha256']:
            raise ValueError('candidate file mismatch: ' + row['path'])
        files[row['path']] = actual
        names.append(row['path'])
    if not names:
        raise ValueError('empty candidate manifest')
    for name in CONSUMED:
        files[name] = digest(source / name)
    value = {'schema_version': 1, 'purpose': 'windows-1677-qualification',
             'candidate_base': manifest['base'], 'candidate_patch_sha256': manifest['patch_sha256'],
             'candidate_manifest_sha256': expected_hash, 'candidate_paths': names,
             'source_files': dict(sorted(files.items())),
             'coverage': 'candidate paths plus explicit consumed control/runtime/test-launcher paths; not whole repository'}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    return value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--candidate-manifest', type=Path, required=True)
    p.add_argument('--candidate-manifest-sha256', required=True)
    p.add_argument('--output', type=Path, required=True, help='new lock file, never overwritten')
    a = p.parse_args()
    value = bind(a.source_root, a.candidate_manifest, a.candidate_manifest_sha256, a.output)
    print(json.dumps({'source_paths': len(value['source_files']), 'candidate_paths': len(value['candidate_paths']),
                      'output_sha256': digest(a.output), 'native_execution': 'NOT_RUN'}))


if __name__ == '__main__':
    main()
