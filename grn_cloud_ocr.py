"""Opt-in OCR.space fallback, with compatibility for existing Azure jobs.

OCR.space contract: https://ocr.space/ocrapi (Engine 2, word overlays).
An upload is never automatically repeated after an ambiguous submission.
"""

import base64
from datetime import datetime
import hashlib
import io
import json
import math
import re
import threading
import time
from urllib.parse import urlsplit

from PIL import Image, ImageOps
import requests

from grn_ocr import RECOGNITION_VERSION, header_number_evidence

API_VERSION = '2024-11-30'
CLOUD_VERSION = RECOGNITION_VERSION + '-azure-read-1'
OCR_SPACE_VERSION = RECOGNITION_VERSION + '-ocr-space-engine2-1'
OCR_SPACE_ENDPOINT = 'https://api.ocr.space/parse/image'
PENDING_STATES = ('Cloud queued', 'Cloud reading')


def validate_endpoint(value):
    value = value.strip().rstrip('/')
    url = urlsplit(value)
    if (url.scheme == 'https' and url.hostname and
            (url.hostname == 'api.ocr.space' or url.hostname.endswith('.ocr.space'))
            and url.path.lower() == '/parse/image' and not url.username and not url.password
            and url.port in (None, 443) and not url.query and not url.fragment):
        return 'https://' + url.hostname + '/parse/image'
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.port not in (None, 443) or url.path or url.query or url.fragment
            or not url.hostname.endswith('.cognitiveservices.azure.com')):
        raise ValueError('Enter an HTTPS OCR.space /parse/image API endpoint, not the website homepage.')
    return 'https://' + url.hostname


def is_ocr_space(endpoint):
    return (urlsplit(endpoint).hostname or '').endswith('.ocr.space')


def recognition_version(endpoint):
    return OCR_SPACE_VERSION if is_ocr_space(endpoint) else CLOUD_VERSION


def credential_target(endpoint):
    provider = 'OCR.space' if is_ocr_space(endpoint) else 'Azure'
    return 'EFL_NEXUS/GRN/' + provider + '/' + hashlib.sha256(validate_endpoint(endpoint).encode()).hexdigest()


def load_credential(endpoint):
    import win32cred
    try:
        item = win32cred.CredRead(credential_target(endpoint), win32cred.CRED_TYPE_GENERIC)
    except Exception as exc:
        if getattr(exc, 'winerror', None) == 1168:
            return ''
        raise RuntimeError('Windows Credential Manager could not read the OCR credential.') from exc
    blob = item['CredentialBlob']
    return blob.decode('utf-16-le') if isinstance(blob, bytes) else blob


def save_credential(endpoint, key):
    import win32cred
    if not key.strip():
        raise ValueError('Enter the OCR API key.')
    try:
        win32cred.CredWrite({'Type': win32cred.CRED_TYPE_GENERIC, 'TargetName': credential_target(endpoint),
                            'UserName': 'GRN cloud OCR', 'CredentialBlob': key.strip().encode('utf-16-le'),
                            'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)
    except Exception as exc:
        raise RuntimeError('Windows Credential Manager could not save the OCR credential.') from exc


def cloud_settings(store):
    config = store.setting('grn_cloud_ocr', {})
    endpoint = config.get('endpoint', OCR_SPACE_ENDPOINT)
    # Earlier UI settings had no provider field. Do not keep automatically
    # uploading to Azure after switching the product's provider to OCR.space.
    enabled = bool(config.get('enabled', False)) and (is_ocr_space(endpoint) or config.get('provider') == 'azure')
    return {'enabled': enabled, 'endpoint': endpoint,
            'daily_limit': config.get('daily_limit', 0)}


def initialize_cloud_tables(store):
    store.db.executescript("""
        CREATE TABLE IF NOT EXISTS grn_cloud_jobs (
            id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL,
            image_hash TEXT NOT NULL, revision INTEGER NOT NULL, version TEXT NOT NULL,
            endpoint TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            operation_url TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
            deadline REAL NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT '{}',
            UNIQUE(document_id,image_hash,revision,version)
        );
        CREATE TABLE IF NOT EXISTS grn_cloud_cache (
            image_hash TEXT NOT NULL, version TEXT NOT NULL, endpoint TEXT NOT NULL,
            result TEXT NOT NULL, PRIMARY KEY(image_hash,version,endpoint)
        );
        CREATE TABLE IF NOT EXISTS grn_cloud_usage (day TEXT PRIMARY KEY, uploads INTEGER NOT NULL);
    """)


def usage_today(store):
    row = store.db.execute('SELECT uploads FROM grn_cloud_usage WHERE day=?', (datetime.now().date().isoformat(),)).fetchone()
    return row[0] if row else 0


def eligible_document(store, job):
    return store.db.execute("""SELECT * FROM grn_documents WHERE id=? AND image_hash=? AND ocr_revision=?
        AND hidden_reason='' AND reviewed=0 AND action='New' AND run_state<>'Running'
        AND state IN ('Cloud queued','Cloud reading') AND NOT EXISTS
        (SELECT 1 FROM grn_sources WHERE document_id=grn_documents.id AND capture_refresh=1)""",
        (job['document_id'], job['image_hash'], job['revision'])).fetchone()


def queue_cloud(store, document_id, image_hash, revision):
    """Called in the local result transaction; this function performs no upload."""
    config = cloud_settings(store)
    if not config['enabled']:
        return False
    try:
        endpoint = validate_endpoint(config['endpoint'])
        if isinstance(config['daily_limit'], bool) or int(config['daily_limit']) < 1:
            return False
    except (TypeError, ValueError):
        return False
    version = recognition_version(endpoint)
    record = store.db.execute("SELECT 1 FROM grn_documents WHERE id=? AND image_hash=? AND ocr_revision=? AND reviewed=0 AND action='New' AND hidden_reason=''",
                              (document_id, image_hash, revision)).fetchone()
    if not record:
        return False
    previous = store.db.execute('SELECT * FROM grn_cloud_jobs WHERE image_hash=? AND version=? AND endpoint=? ORDER BY id DESC LIMIT 1',
                                (image_hash, version, endpoint)).fetchone()
    store.db.execute("""INSERT INTO grn_cloud_jobs(document_id,image_hash,revision,version,endpoint)
        VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING""", (document_id, image_hash, revision, version, endpoint))
    store.db.execute("UPDATE grn_documents SET state='Cloud queued' WHERE id=? AND image_hash=? AND ocr_revision=? AND reviewed=0 AND action='New' AND hidden_reason=''",
                     (document_id, image_hash, revision))
    if previous and previous['revision'] != revision:
        if previous['status'] in ('uncertain', 'submitting'):
            store.db.execute("UPDATE grn_cloud_jobs SET status='uncertain',error=? WHERE document_id=? AND revision=? AND version=?",
                             ('Previous cloud submission is uncertain. Check provider usage before Retry Cloud.', document_id, revision, version))
            store.db.execute("UPDATE grn_documents SET state='Ready for review' WHERE id=?", (document_id,))
            store.db.execute("INSERT OR REPLACE INTO monitor_settings VALUES('grn_cloud_status',?)",
                             (json.dumps('Previous cloud upload is uncertain. Retry Cloud explicitly to upload again.'),))
        elif previous['operation_url'] and previous['status'] != 'complete':
            store.db.execute("UPDATE grn_cloud_jobs SET status='polling',operation_url=?,deadline=? WHERE document_id=? AND revision=? AND version=?",
                             (previous['operation_url'], previous['deadline'], document_id, revision, version))
    return True


def prepare_upload(record, max_bytes=4 * 1024 * 1024):
    local = json.loads(record['extraction'])
    path = local.get('header_path') or local.get('working_path') or record['image_path']
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
    # Apply the provider's byte limit without downscaling away printed detail.
    for quality in (95, 85, 75):
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=quality)
        data = buffer.getvalue()
        if len(data) <= max_bytes:
            return data
    raise ValueError(f'Cloud image exceeds the {max_bytes:,}-byte upload limit. Crop the header or review manually.')


def parse_azure_result(payload):
    """Normalize documented polygons into upright word boxes, then apply header rules."""
    candidates, evidence = set(), []
    for page in payload.get('analyzeResult', {}).get('pages', []):
        width, height = float(page['width']), float(page['height'])
        angle = math.radians(float(page.get('angle', 0)))
        cosine, sine = math.cos(angle), math.sin(angle)
        upright_width = abs(cosine)*width + abs(sine)*height
        upright_height = abs(sine)*width + abs(cosine)*height
        words = []
        for word in page.get('words', []):
            polygon = word.get('polygon', [])
            if len(polygon) != 8:
                continue
            points = [(cosine*(x-width/2)+sine*(y-height/2)+upright_width/2,
                       -sine*(x-width/2)+cosine*(y-height/2)+upright_height/2)
                      for x, y in zip(polygon[::2], polygon[1::2])]
            xs, ys = zip(*points)
            words.append({'text': word.get('content', ''), 'confidence': float(word.get('confidence', 0))*100,
                          'left': min(xs), 'top': min(ys), 'width': max(xs)-min(xs), 'height': max(ys)-min(ys)})
        for word in header_number_evidence(words, (upright_width, upright_height)):
            candidates.add(word['text'])
            evidence.append({'source': 'Azure', 'value': word['text'], 'confidence': word['confidence'],
                             'box': [word['left'], word['top'], word['width'], word['height']]})
    return {'azure_candidates': sorted(candidates), 'evidence': evidence}


def merge_cloud_result(local, cloud):
    result = dict(local)
    key = 'ocr_space_candidates' if 'ocr_space_candidates' in cloud else 'azure_candidates'
    provider = 'OCR.space' if key == 'ocr_space_candidates' else 'Azure'
    values = set(local.get('ocr_candidates', [])) | set(local.get('barcode_candidates', [])) | set(cloud[key])
    result.update({key: cloud[key]}, recognition_version=OCR_SPACE_VERSION if provider == 'OCR.space' else CLOUD_VERSION,
                  recognition_source=local.get('recognition_source', 'local') + ' + ' + provider, processing_status='cloud_complete')
    result['gatepass'] = next(iter(values)) if len(values) == 1 else ''
    result['evidence'] = local.get('evidence', []) + cloud.get('evidence', [])
    result['warnings'] = ['Local attempt: ' + w for w in local.get('warnings', [])]
    if len(values) > 1:
        result['warnings'].append(f'Local OCR, barcode or {provider} readings disagree. Enter the number manually.')
    if not cloud[key]:
        result['warnings'].append(f'{provider} found no unambiguous number beside the GATE PASS header.')
    if any(w.get('confidence') is not None and w['confidence'] < 60 for w in cloud.get('evidence', [])):
        result['warnings'].append(f'Low-confidence {provider} reading; compare every digit with the photo.')
    if provider == 'OCR.space':
        result['warnings'].append('OCR.space does not supply word confidence scores. Verify the printed number.')
    return result


def parse_ocr_space_result(payload, size):
    """Read documented word overlays; plain text alone cannot establish a header."""
    if payload.get('IsErroredOnProcessing') is not False or str(payload.get('OCRExitCode')) != '1':
        raise RuntimeError('OCR.space could not process this image. Check the API key, service quota and file size, then retry explicitly.')
    pages = payload.get('ParsedResults')
    if not isinstance(pages, list) or not pages:
        raise ValueError('OCR.space returned no image results. Review manually.')
    candidates, evidence = set(), []
    width, height = size
    for page in pages:
        if str(page.get('FileParseExitCode')) != '1':
            raise RuntimeError('OCR.space could not parse the image completely. Review manually or retry explicitly.')
        overlay = page.get('TextOverlay') or {}
        if overlay.get('HasOverlay') is not True:
            raise ValueError('OCR.space returned no word positions. The GATE PASS header could not be verified.')
        words = []
        for line in overlay.get('Lines', []):
            for word in line.get('Words', []):
                box = {k: float(word[name]) for k, name in (('left', 'Left'), ('top', 'Top'), ('width', 'Width'), ('height', 'Height'))}
                if not all(math.isfinite(v) for v in box.values()) or box['width'] <= 0 or box['height'] <= 0:
                    raise ValueError('OCR.space returned invalid word positions. Review manually.')
                words.append({'text': word['WordText'], 'confidence': None, **box})
        # Autorotation/upscaling is disabled in the request. Try the four
        # orthogonal coordinate frames without guessing or changing any digits.
        for degrees in (0, 90, 180, 270):
            angle = math.radians(degrees)
            cosine, sine = math.cos(angle), math.sin(angle)
            w, h = abs(cosine)*width+abs(sine)*height, abs(sine)*width+abs(cosine)*height
            oriented = []
            for word in words:
                x, y, bw, bh = word['left'], word['top'], word['width'], word['height']
                points = [(cosine*(px-width/2)+sine*(py-height/2)+w/2,
                           -sine*(px-width/2)+cosine*(py-height/2)+h/2)
                          for px, py in ((x,y),(x+bw,y),(x,y+bh),(x+bw,y+bh))]
                xs, ys = zip(*points)
                oriented.append({**word, 'left': min(xs), 'top': min(ys), 'width': max(xs)-min(xs), 'height': max(ys)-min(ys)})
            for word in header_number_evidence(oriented, (w, h)):
                candidates.add(word['text'])
                evidence.append({'source': 'OCR.space', 'value': word['text'], 'confidence': None,
                                 'box': [word['left'], word['top'], word['width'], word['height']]})
    return {'ocr_space_candidates': sorted(candidates), 'evidence': evidence}


class OCRSpaceClient:
    def __init__(self, endpoint, key):
        self.endpoint = validate_endpoint(endpoint)
        if not is_ocr_space(self.endpoint):
            raise ValueError('Choose an OCR.space API endpoint.')
        self.headers = {'apikey': key}

    def submit(self, data):
        response = requests.post(self.endpoint, headers=self.headers,
                                 files={'file': ('grn-photo.jpg', data, 'image/jpeg')},
                                 data={'OCREngine': '2', 'isOverlayRequired': 'true', 'detectOrientation': 'false',
                                       'scale': 'false', 'isCreateSearchablePdf': 'false'},
                                 timeout=(5, 55), allow_redirects=False)
        if response.status_code >= 500:
            raise requests.RequestException('OCR.space submission outcome is uncertain.')
        if response.status_code != 200:
            detail = {401: 'OCR.space API key is invalid.', 403: 'OCR.space denied access. Check your API key.',
                      429: 'OCR.space rate limit or quota reached. Retry later.', 413: 'OCR.space rejected the image size.'}
            raise RuntimeError(detail.get(response.status_code, f'OCR.space returned HTTP {response.status_code}. Retry explicitly or review manually.'))
        return response.json()


class AzureReadClient:
    def __init__(self, endpoint, key):
        self.endpoint = validate_endpoint(endpoint)
        self.headers = {'Ocp-Apim-Subscription-Key': key}

    def operation_url(self, value):
        url = urlsplit(value)
        if (url.scheme != 'https' or url.netloc != urlsplit(self.endpoint).netloc
                or not url.path.startswith('/documentintelligence/documentModels/prebuilt-read/analyzeResults/')
                or url.username or url.password or url.fragment):
            raise ValueError('Azure returned an invalid operation address; no credential was sent to it.')
        return value

    @staticmethod
    def check_response(response, expected):
        if response.status_code != expected:
            detail = {401: 'Azure key or resource is invalid.', 403: 'Azure denied access to this resource.',
                      429: 'Azure quota or rate limit reached. Retry later.', 404: 'Azure resource or operation was not found.'}
            raise RuntimeError(detail.get(response.status_code, f'Azure returned HTTP {response.status_code}. Review or retry later.'))

    def submit(self, data):
        response = requests.post(self.endpoint + '/documentintelligence/documentModels/prebuilt-read:analyze',
                                 params={'api-version': API_VERSION}, headers=self.headers,
                                 json={'base64Source': base64.b64encode(data).decode('ascii')},
                                 timeout=(5, 20), allow_redirects=False)
        if response.status_code >= 500:
            raise requests.RequestException('Azure submission outcome is uncertain.')
        self.check_response(response, 202)
        return self.operation_url(response.headers.get('Operation-Location', ''))

    def poll(self, operation, remaining=15):
        response = requests.get(self.operation_url(operation), headers=self.headers,
                                timeout=(min(5, remaining/2), min(15, remaining/2)), allow_redirects=False)
        self.check_response(response, 200)
        return response.json(), max(1, int(response.headers.get('Retry-After', '1')))


class GRNCloudWorker:
    def __init__(self, db_path, stopping):
        self.db_path, self.stopping = db_path, stopping
        self.thread = threading.Thread(target=self.run, name='GRN cloud OCR', daemon=True)

    @staticmethod
    def release_reviewed(store, job):
        store.db.execute("""UPDATE grn_documents SET state='Ready for review' WHERE id=? AND image_hash=?
            AND ocr_revision=? AND reviewed=1 AND hidden_reason='' AND state IN ('Cloud queued','Cloud reading')""",
                         (job['document_id'], job['image_hash'], job['revision']))

    def finish(self, store, job, cloud):
        with store.db:
            store.db.execute('BEGIN IMMEDIATE')
            record = eligible_document(store, job)
            if record:
                merged = merge_cloud_result(json.loads(record['extraction']), cloud)
                store.db.execute("UPDATE grn_documents SET state='Ready for review',extraction=?,gatepass=? WHERE id=?",
                                 (json.dumps(merged), merged['gatepass'], record['id']))
            self.release_reviewed(store, job)
            store.db.execute("UPDATE grn_cloud_jobs SET status='complete',result=?,error='' WHERE id=?", (json.dumps(cloud), job['id']))
            store.db.execute('INSERT OR REPLACE INTO grn_cloud_cache VALUES(?,?,?,?)',
                             (job['image_hash'], job['version'], job['endpoint'], json.dumps(cloud)))

    def fail(self, store, job, message, status='error'):
        with store.db:
            store.db.execute('BEGIN IMMEDIATE')
            record = eligible_document(store, job)
            if record:
                result = json.loads(record['extraction'])
                result['processing_status'] = 'cloud_' + status
                result['warnings'] = result.get('warnings', []) + [message]
                store.db.execute("UPDATE grn_documents SET state='Ready for review',extraction=? WHERE id=?", (json.dumps(result), record['id']))
            self.release_reviewed(store, job)
            store.db.execute('UPDATE grn_cloud_jobs SET status=?,error=? WHERE id=?', (status, message, job['id']))
        store.set_settings(grn_cloud_status=message)

    def process_one(self, store):
        job = store.db.execute("SELECT * FROM grn_cloud_jobs WHERE status IN ('queued','polling') ORDER BY id LIMIT 1").fetchone()
        if not job:
            return False
        job = dict(job)
        if not eligible_document(store, job):
            with store.db:
                store.db.execute("UPDATE grn_cloud_jobs SET status='cancelled' WHERE id=?", (job['id'],))
                self.release_reviewed(store, job)
            return True
        config = cloud_settings(store)
        if not config['enabled'] or config['endpoint'] != job['endpoint']:
            self.fail(store, job, 'Cloud OCR disabled or resource changed. Review manually or retry extraction.', 'paused')
            return True
        try:
            cached = store.db.execute('SELECT result FROM grn_cloud_cache WHERE image_hash=? AND version=? AND endpoint=?',
                                      (job['image_hash'], job['version'], job['endpoint'])).fetchone()
            if cached:
                self.finish(store, job, json.loads(cached[0]))
                return True
            key = load_credential(job['endpoint'])
            if not key:
                raise ValueError('OCR API key is missing. Open OCR Settings and save the provider key.')
            space = is_ocr_space(job['endpoint'])
            client = OCRSpaceClient(job['endpoint'], key) if space else AzureReadClient(job['endpoint'], key)
            if job['status'] == 'queued':
                data = prepare_upload(eligible_document(store, job), max_bytes=1_000_000 if space else 4*1024*1024)
                with store.db:
                    store.db.execute('BEGIN IMMEDIATE')
                    if not eligible_document(store, job):
                        return True
                    current = store.db.execute('SELECT status FROM grn_cloud_jobs WHERE id=?', (job['id'],)).fetchone()
                    if current is None or current['status'] != 'queued':
                        return True
                    latest = cloud_settings(store)
                    if not latest['enabled'] or latest['endpoint'] != job['endpoint']:
                        raise ValueError('Cloud OCR was disabled or the resource changed before upload.')
                    limit = int(latest['daily_limit'])
                    if usage_today(store) >= limit or limit < 1:
                        raise ValueError('Daily cloud upload limit reached. Review manually or retry on another day.')
                    day = datetime.now().date().isoformat()
                    store.db.execute('INSERT INTO grn_cloud_usage VALUES(?,1) ON CONFLICT(day) DO UPDATE SET uploads=uploads+1', (day,))
                    store.db.execute("UPDATE grn_cloud_jobs SET status='submitting' WHERE id=? AND status='queued'", (job['id'],))
                    store.db.execute("UPDATE grn_documents SET state='Cloud reading' WHERE id=?", (job['document_id'],))
                # No automatic POST retries. A timeout may still have incurred a charge.
                try:
                    response = client.submit(data)
                except (requests.RequestException, ValueError):
                    self.fail(store, job, 'Cloud submission outcome is uncertain. Check provider usage; Retry Cloud explicitly to upload again.', 'uncertain')
                    return True
                if space:
                    with Image.open(io.BytesIO(data)) as uploaded:
                        cloud = parse_ocr_space_result(response, uploaded.size)
                    self.finish(store, job, cloud)
                    store.set_settings(grn_cloud_status='OCR.space reading complete. Check the number and warehouse.')
                    return True
                operation = response
                job.update(operation_url=operation, deadline=time.time()+60, status='polling')
                with store.db:
                    store.db.execute("UPDATE grn_cloud_jobs SET status='polling',operation_url=?,deadline=? WHERE id=?",
                                     (operation, job['deadline'], job['id']))
            while not self.stopping.is_set():
                if not eligible_document(store, job) or not cloud_settings(store)['enabled']:
                    self.fail(store, job, 'Cloud reading cancelled; saved review and visibility are preserved.', 'cancelled')
                    return True
                remaining = job['deadline'] - time.time()
                if remaining <= 0:
                    self.fail(store, job, 'Azure reading reached its 60-second wait limit. Retry Cloud to poll the accepted request without uploading again.', 'timeout')
                    return True
                payload, delay = client.poll(job['operation_url'], max(.01, remaining))
                if payload.get('status') == 'succeeded':
                    self.finish(store, job, parse_azure_result(payload))
                    store.set_settings(grn_cloud_status='Azure reading complete. Check the number and warehouse.')
                    return True
                if payload.get('status') == 'failed':
                    raise ValueError('Azure could not read this photo. Review manually or retry extraction.')
                if payload.get('status') not in ('running', 'notStarted'):
                    raise ValueError('Azure returned an unsupported processing status. Review manually.')
                self.stopping.wait(min(delay, remaining))
        except (requests.RequestException, RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            message = 'Cloud OCR connection failed. Check the network and retry explicitly.' if isinstance(exc, requests.RequestException) else str(exc)
            self.fail(store, job, message)
        return True

    def run(self):
        from whatsapp_grn import GRNInboxStore
        store = GRNInboxStore(self.db_path)
        try:
            # A crash between committing upload intent and saving its handle is ambiguous.
            for job in store.db.execute("SELECT * FROM grn_cloud_jobs WHERE status='submitting'").fetchall():
                self.fail(store, dict(job), 'Interrupted cloud submission has an uncertain outcome. Check provider usage before Retry Cloud.', 'uncertain')
            while not self.stopping.is_set():
                if not self.process_one(store):
                    self.stopping.wait(.5)
        except Exception:
            store.set_settings(grn_cloud_status='Cloud OCR worker stopped. Reconnect WhatsApp to resume; accepted requests are retained.')
        finally:
            store.close()


def retry_cloud(store, record_id):
    """An explicit retry may resubmit an uncertain upload; accepted jobs only poll."""
    config = cloud_settings(store)
    if not config['enabled']:
        raise ValueError('Enable cloud OCR in OCR Settings before retrying a cloud request.')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        row = store.db.execute("""SELECT j.* FROM grn_cloud_jobs j JOIN grn_documents d ON d.id=j.document_id AND d.image_hash=j.image_hash AND d.ocr_revision=j.revision
            WHERE d.id=? AND d.hidden_reason='' AND d.reviewed=0 AND d.action='New' AND d.run_state<>'Running' ORDER BY j.id DESC LIMIT 1""", (record_id,)).fetchone()
        if not row:
            raise ValueError('No retryable cloud request for this unreviewed photo. Use Retry Extraction after configuring cloud OCR.')
        if row['endpoint'] != config['endpoint']:
            raise ValueError('The cloud OCR endpoint changed. Use Retry Extraction for the configured service.')
        if row['status'] in ('queued', 'submitting', 'polling'):
            raise ValueError('Cloud OCR is already queued or running for this photo.')
        if row['status'] == 'complete':
            raise ValueError('This cloud result is already cached. Review the number or retry extraction.')
        status = 'polling' if row['operation_url'] else 'queued'
        store.db.execute('UPDATE grn_cloud_jobs SET status=?,error=\'\',deadline=? WHERE id=?', (status, time.time()+60, row['id']))
        store.db.execute("UPDATE grn_documents SET state='Cloud queued' WHERE id=?", (record_id,))
