import os
import json
import csv
from datetime import datetime
from flask import Flask, render_template, send_from_directory, jsonify, request
from uvicorn.middleware.wsgi import WSGIMiddleware


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
TRACES_DIR = os.path.join(PROJECT_ROOT, 'annotation', 'traces')
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

os.makedirs(DATA_DIR, exist_ok=True)

LABELS_JSONL = os.path.join(DATA_DIR, 'labels.jsonl')

app = Flask(__name__, static_folder=STATIC_DIR, template_folder=TEMPLATES_DIR)
asgi_app = WSGIMiddleware(app)


def list_trace_files():
    """Return a flattened list of trace identifiers.

    Supports two formats in TRACES_DIR:
    - Single-object JSON files: one trace per file → identifier is the filename
    - Array-of-objects JSON files: multiple traces in one file → identifiers are
      "filename#ts" for each entry, where ts is the entry's timestamp field
    """
    ids = []
    for fname in sorted([f for f in os.listdir(TRACES_DIR) if f.endswith('.json')]):
        path = os.path.join(TRACES_DIR, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            # Skip unreadable files
            continue
        if isinstance(raw, list):
            for entry in raw:
                ts = entry.get('ts') or ''
                # Only include entries that look like valid traces
                if isinstance(entry, dict) and 'response' in entry:
                    ids.append(f"{fname}#{ts}" if ts else f"{fname}#")
        elif isinstance(raw, dict):
            ids.append(fname)
    return ids


def load_trace(file_id: str):
    """Load trace by identifier.

    file_id may be a plain filename (single-object trace) or
    "filename#ts" to select a specific entry from an array-of-traces file.
    """
    if '#' in file_id:
        filename, entry_ts = file_id.split('#', 1)
    else:
        filename, entry_ts = file_id, None
    path = os.path.join(TRACES_DIR, filename)
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    # If array, choose the entry by ts when provided; otherwise take the last
    if isinstance(raw, list) and raw:
        if entry_ts:
            selected = None
            for entry in raw:
                if isinstance(entry, dict) and str(entry.get('ts', '')) == entry_ts:
                    selected = entry
                    break
            data = selected or raw[-1]
        else:
            data = raw[-1]
    else:
        data = raw
    # Extract initial query and last assistant response
    request_messages = data.get('request', {}).get('messages', [])
    response_messages = data.get('response', {}).get('messages', [])
    # assistant output: last assistant message content in response
    assistant_output = ''
    last_assistant_idx = None
    for i in range(len(response_messages) - 1, -1, -1):
        if response_messages[i].get('role') == 'assistant':
            assistant_output = response_messages[i].get('content', '')
            last_assistant_idx = i
            break
    # relevant query: the user message immediately preceding the last assistant
    initial_query = ''
    if last_assistant_idx is not None:
        for j in range(last_assistant_idx - 1, -1, -1):
            if response_messages[j].get('role') == 'user':
                initial_query = response_messages[j].get('content', '')
                break
    # If not found in response thread, fall back to last user in response, then request
    if not initial_query:
        for m in reversed(response_messages):
            if m.get('role') == 'user':
                initial_query = m.get('content', '')
                break
    if not initial_query:
        for m in reversed(request_messages):
            if m.get('role') == 'user':
                initial_query = m.get('content', '')
                break
    return {
        'filename': file_id,
        'initial_query': initial_query,
        'assistant_output': assistant_output,
    }


def read_labels_index():
    labels = {}
    if os.path.exists(LABELS_JSONL):
        with open(LABELS_JSONL, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                labels[row.get('filename')] = row
    return labels


@app.route('/')
def index():
    files = list_trace_files()
    return render_template('index.html', files=files)


@app.route('/api/trace/<int:index>')
def get_trace(index: int):
    files = list_trace_files()
    if not files:
        return jsonify({'error': 'No traces found'}), 404
    index = max(0, min(index, len(files) - 1))
    filename = files[index]
    payload = load_trace(filename)
    payload.update({'index': index, 'total': len(files)})
    labels = read_labels_index()
    payload['existing_label'] = labels.get(filename)
    return jsonify(payload)


@app.route('/api/save', methods=['POST'])
def save_label():
    body = request.get_json(force=True)
    filename = body.get('filename')
    feedback = body.get('feedback', '')
    verdict = body.get('verdict')  # 'up' or 'down'
    index = body.get('index')
    if not filename:
        return jsonify({'error': 'filename required'}), 400

    record = {
        'filename': filename,
        'feedback': feedback,
        'verdict': verdict,
        'index': index,
        'saved_at': datetime.utcnow().isoformat() + 'Z',
    }

    # Append or replace existing entry for this filename by rewriting file
    existing = []
    seen = False
    if os.path.exists(LABELS_JSONL):
        with open(LABELS_JSONL, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get('filename') == filename:
                    row = record
                    seen = True
                existing.append(row)
    if not seen:
        existing.append(record)
    with open(LABELS_JSONL, 'w', encoding='utf-8') as f:
        for row in existing:
            f.write(json.dumps(row) + '\n')

    return jsonify({'status': 'ok', 'record': record})


@app.route('/api/labels')
def list_labels():
    labels = []
    if os.path.exists(LABELS_JSONL):
        with open(LABELS_JSONL, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    labels.append(json.loads(line))
                except Exception:
                    continue
    return jsonify({'labels': labels})


@app.route('/api/export')
def export_csv():
    # Export labels to CSV alongside filename and basic fields
    csv_name = f"labels_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    csv_path = os.path.join(DATA_DIR, csv_name)
    labels = []
    if os.path.exists(LABELS_JSONL):
        with open(LABELS_JSONL, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    labels.append(json.loads(line))
                except Exception:
                    continue
    fieldnames = ['filename', 'index', 'verdict', 'feedback', 'saved_at']
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in labels:
            writer.writerow({fn: row.get(fn) for fn in fieldnames})
    # Serve the file
    return send_from_directory(DATA_DIR, csv_name, as_attachment=True)


@app.route('/static/<path:path>')
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


def run():
    app.run(host='0.0.0.0', port=5050, debug=True)


if __name__ == '__main__':
    run()


