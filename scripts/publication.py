"""Separate private/public outputs; transcript sharing is opt-in and content-bound."""
import copy
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

OMITTED = "Transcript omitted for privacy."
# Explicit schema: new pipeline fields are private until deliberately reviewed here.
PUBLIC_FIELDS = set('''id lang language date time duration_sec total_words unique_words
 ttr mattr_50 wpm articulation_wpm speech_ratio speech_time_sec pause_time_sec
 num_pauses pauses_over_2s pauses_over_5s mean_inter_word_gap max_pause_sec
 longest_run_words longest_run_sec avg_word_length pct_words_7plus_chars filler_count
 fillers_per_min lookup_questions pause_threshold_sec hallucinated_words_removed
 transcription_backend metrics_backend transcript_word_count transcription_note
 pipeline_version analysis analysis_md proficiency'''.split())
RAW_KEYS = {'transcript', 'transcript_text', 'transcript_json', 'raw_transcript',
            'timing_text', 'words', 'segments', 'audio', 'audio_url', 'api_response'}


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def load_approvals(root):
    path = root / 'config/transcript-sharing.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if data.get('version') != 1 or not isinstance(data.get('approved'), dict):
        raise ValueError('Invalid transcript-sharing.json; refusing public build')
    for key, value in data['approved'].items():
        if not isinstance(value, dict) or not re.fullmatch(r'[a-f0-9]{64}', value.get('sha256', '')):
            raise ValueError(f'Invalid approval for {key}; refusing public build')
    return data['approved']


def sharing_state(record, approvals):
    approval = approvals.get(record['id'])
    if not approval:
        return 'omitted'
    return 'approved' if record.get('transcript') and approval['sha256'] == digest(record['transcript']) else 'changed'


def without_raw_fields(value):
    if isinstance(value, dict):
        return {k: without_raw_fields(v) for k, v in value.items() if k not in RAW_KEYS}
    if isinstance(value, list):
        return [without_raw_fields(v) for v in value]
    return value


def public_records(records, approvals):
    output = []
    for record in records:
        public = without_raw_fields(copy.deepcopy({k: v for k, v in record.items() if k in PUBLIC_FIELDS}))
        approved = sharing_state(record, approvals) == 'approved'
        public['transcript_visibility'] = 'approved' if approved else 'omitted'
        public['transcript'] = record['transcript'] if approved else OMITTED
        output.append(public)
    return output


def javascript(records, methodology, audience):
    return ('window.SESSIONS = ' + json.dumps(records, ensure_ascii=False) + ';\n'
            + 'window.PROFICIENCY_METHOD = ' + json.dumps(methodology, ensure_ascii=False) + ';\n'
            + 'window.SITE_AUDIENCE = ' + json.dumps(audience) + ';\n')


def versioned_index(template, data):
    return re.sub(r'<script src="data\.js(?:\?v=[^"]*)?"></script>',
                  f'<script src="data.js?v={digest(data)[:12]}"></script>', template, count=1)


def build(root, records):
    approvals = load_approvals(root)
    private = copy.deepcopy(records)
    for record in private:
        record['public_transcript_status'] = sharing_state(record, approvals)
    methodology_path = root / 'docs/proficiency-methodology.md'
    methodology = methodology_path.read_text() if methodology_path.exists() else ''
    explorer = root / 'explorer'
    explorer.mkdir(exist_ok=True)
    private_js = javascript(private, methodology, 'private')
    (explorer / 'data.js').write_text(private_js)
    index_path = explorer / 'index.html'
    if not index_path.exists():  # Data-only pipeline/test use.
        return
    template = index_path.read_text()
    index_path.write_text(versioned_index(template, private_js))
    # Only touch the designated generated directory, never copy the workspace.
    public_dir = root / 'build/public'
    if public_dir.exists():
        shutil.rmtree(public_dir)
    public_dir.mkdir(parents=True)
    public = public_records(records, approvals)
    public_js = javascript(public, methodology, 'public')
    (public_dir / 'data.js').write_text(public_js)
    (public_dir / 'index.html').write_text(versioned_index(template, public_js))
    (public_dir / '.nojekyll').write_text('')
    deploy_config = root / 'config/publishing.json'
    if deploy_config.exists():
        domain = json.loads(deploy_config.read_text()).get('public_domain')
        if domain:
            if not re.fullmatch(r'[a-z0-9.-]+', domain):
                raise ValueError('Invalid public_domain')
            (public_dir / 'CNAME').write_text(domain + '\n')
    # The Sites source checkout retains full text, exactly matching this rebuild.
    if (root / 'site/.openai/hosting.json').exists():
        destination = root / 'site/public/explorer'
        destination.mkdir(parents=True, exist_ok=True)
        for name in ('index.html', 'data.js'):
            shutil.copy2(explorer / name, destination / name)
    approved = sum(r['transcript_visibility'] == 'approved' for r in public)
    print(f'public build: {len(public)} sessions, {approved} approved transcripts, {len(public)-approved} omitted')


def set_approval(root, session_id, approve):
    if not re.fullmatch(r'[a-z]{2}/\d{4}-\d{2}-\d{2}_\d{4}', session_id):
        raise ValueError('Use an exact session ID: lang/YYYY-MM-DD_HHMM')
    approvals = load_approvals(root)
    if approve:
        transcript = (root / 'sessions' / session_id / 'transcript.txt').read_text().strip()
        if not transcript:
            raise ValueError('Cannot approve an empty transcript')
        approvals[session_id] = {'sha256': digest(transcript),
                                'approved_at': datetime.now(timezone.utc).isoformat()}
    else:
        approvals.pop(session_id, None)
    path = root / 'config/transcript-sharing.json'
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'version': 1, 'approved': approvals}, indent=2) + '\n')
    tmp.replace(path)
    print(f'{session_id}: {"approved" if approve else "omitted"} for next public publication')
