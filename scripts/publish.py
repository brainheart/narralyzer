#!/usr/bin/env python3
"""Build both audiences, audit the public export, and optionally push GitHub Pages.

The private Sites deployment is finalized through native Sites tools; see
 docs/publishing.md. This command never copies private Git history or sessions.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

import publication

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILES = (
    'README.md', 'AGENTS.md', 'requirements.txt', '.gitignore',
    'scripts/narralyze.py', 'scripts/proficiency.py', 'scripts/publication.py',
    'scripts/publish.py', 'scripts/configure_api_key.py',
    'tests/test_narralyze.py', 'tests/test_proficiency.py', 'tests/test_publication.py',
    'docs/analysis-format.md', 'docs/proficiency-methodology.md',
    'docs/transcription.md', 'docs/publishing.md', 'docs/narralogue.md', 'explorer/index.html',
)


def run(args, cwd=ROOT, **kwargs):
    return subprocess.run(args, cwd=cwd, check=True, **kwargs)


def export_files(root):
    files = {name: (root / name).read_bytes() for name in SOURCE_FILES}
    for path in (root / 'build/public').iterdir():
        if path.name not in {'index.html', 'data.js', '.nojekyll', 'CNAME'} or not path.is_file():
            raise ValueError(f'Unexpected public build file: {path.name}')
        files[path.name] = path.read_bytes()
    # A reusable template, never the owner's list of sharing decisions or Sites ID.
    files['config/transcript-sharing.json'] = b'{"version": 1, "approved": {}}\n'
    files['config/publishing.example.json'] = b'{"public_repository": "YOUR-USER/YOUR-REPO", "public_domain": null}\n'
    return files


def audit(root, files):
    records = json.loads((root / 'data/sessions.json').read_text())
    approvals = publication.load_approvals(root)
    expected = publication.public_records(records, approvals)
    line = files['data.js'].decode().splitlines()[0]
    actual = json.loads(line.removeprefix('window.SESSIONS = ').removesuffix(';'))
    if actual != expected:
        raise ValueError('Public data does not match the current sharing policy')
    # Catch accidental full transcripts in any artifact or source file, including
    # JSON-escaped copies. Short evidence quotes remain intentionally public.
    for record in records:
        transcript = record.get('transcript', '')
        if transcript and publication.sharing_state(record, approvals) != 'approved':
            needles = {transcript.encode(), json.dumps(transcript, ensure_ascii=False)[1:-1].encode(),
                       json.dumps(transcript, ensure_ascii=True)[1:-1].encode()}
            for name, content in files.items():
                if any(needle in content for needle in needles):
                    raise ValueError(f'Unapproved full transcript found in {name}: {record["id"]}')
    return len(records)


def publish_public(root, files, repository):
    checkout = root / '.publication/github'
    expected_url = f'https://github.com/{repository}.git'
    if not (checkout / '.git').exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        run(['git', 'clone', expected_url, str(checkout)], cwd=root)
    origin = run(['git', 'remote', 'get-url', 'origin'], cwd=checkout, capture_output=True, text=True).stdout.strip()
    if origin != expected_url:
        raise ValueError('Public checkout remote does not match publishing.json')
    run(['git', 'fetch', 'origin'], cwd=checkout)
    remote = run(['git', 'ls-remote', '--heads', 'origin', 'main'], cwd=checkout, capture_output=True, text=True).stdout.strip()
    if remote:
        run(['git', 'merge', '--ff-only', 'origin/main'], cwd=checkout)
    else:
        run(['git', 'checkout', '-B', 'main'], cwd=checkout)
    existing = {str(p.relative_to(checkout)) for p in checkout.rglob('*')
                if p.is_file() and '.git' not in p.relative_to(checkout).parts}
    unexpected = existing - files.keys()
    if unexpected:
        raise ValueError(f'Unexpected files in public checkout; review before publishing: {sorted(unexpected)}')
    for name, content in files.items():
        dest = checkout / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    # Stage only our allowlisted export. Never use git add on the private workspace.
    run(['git', 'add', '--force', '--', *files.keys()], cwd=checkout)
    status = run(['git', 'diff', '--cached', '--name-only'], cwd=checkout, capture_output=True, text=True).stdout
    if status.strip():
        run(['git', 'commit', '-m', 'Publish Narralyzer with approved transcripts only'], cwd=checkout)
    run(['git', 'push', 'origin', 'HEAD:main'], cwd=checkout)
    return run(['git', 'rev-parse', 'HEAD'], cwd=checkout, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', action='store_true', help='Push audited public files to the configured GitHub Pages repository')
    args = parser.parse_args()
    run([sys.executable, 'scripts/narralyze.py', 'rebuild'])
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'])
    files = export_files(ROOT)
    count = audit(ROOT, files)
    print(f'Audited {len(files)} public files covering {count} sessions.', flush=True)
    if args.public:
        config = json.loads((ROOT / 'config/publishing.json').read_text())
        commit = publish_public(ROOT, files, config['public_repository'])
        print(f'GitHub Pages source pushed: {commit}', flush=True)
    print('Private source synchronized at site/public/explorer. Finish Sites packaging and native deployment using docs/publishing.md.', flush=True)


if __name__ == '__main__':
    main()
