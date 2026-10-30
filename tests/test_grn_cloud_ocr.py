"""Real SQLite lifecycle checks; Azure HTTP/credential doubles are test-only.

No request in this file reaches Azure, and no real credential is read or written.
"""

import base64
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
import requests

from grn_cloud_ocr import (AzureReadClient, CLOUD_VERSION, GRNCloudWorker, cloud_settings,
                           merge_cloud_result, parse_azure_result, queue_cloud, retry_cloud,
                           usage_today, validate_endpoint, OCR_SPACE_ENDPOINT, OCR_SPACE_VERSION,
                           OCRSpaceClient, parse_ocr_space_result, credential_target)
from whatsapp_grn import GRNInboxStore, GRNExtractionWorker, fill_grn_request
from grn_ocr_settings import GRNOCRSettings

# Explicit test-only resource and operation addresses; HTTP is replaced below.
ENDPOINT = 'https://test-only-resource.cognitiveservices.azure.com'
OPERATION = ENDPOINT + '/documentintelligence/documentModels/prebuilt-read/analyzeResults/test-operation?api-version=2024-11-30'


def azure_payload_double(number='000123', angle=0):
    """Minimal documented Azure word/polygon response shape, not a real reading."""
    words = [{'content': text, 'confidence': .99, 'polygon': [x, 100, x+w, 100, x+w, 130, x, 130]}
             for text, x, w in [('GATE', 100, 70), ('PASS:', 180, 70), (number, 270, 120)]]
    return {'status': 'succeeded', 'analyzeResult': {'pages': [{'width': 1000, 'height': 1400,
                                                              'angle': angle, 'words': words}]}}


def response_double(status, payload=None, **headers):
    """A real requests.Response carrying an explicitly synthetic HTTP response."""
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers)
    response._content = json.dumps(payload or {}).encode()
    return response


class CloudQueueTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.store = GRNInboxStore(self.folder / 'inbox.sqlite3')
        self.addCleanup(self.store.close)
        self.worker = GRNCloudWorker(self.store.path, threading.Event())
        self.store.set_settings(grn_cloud_ocr={'provider': 'azure', 'enabled': True, 'endpoint': ENDPOINT, 'daily_limit': 2})
        self.key_double = patch('grn_cloud_ocr.load_credential', return_value='test-double-key')
        self.key_double.start()
        self.addCleanup(self.key_double.stop)

    def document(self, color='white', local=None):
        self.store.discover({'group_id': 'test-only-group', 'name': 'Test group', 'messages': [],
                             'photos': [{'message_id': color, 'index': 0}]})
        source = next(row for row in self.store.pending_entries() if row['message_id'] == color)
        data = io.BytesIO()
        Image.new('RGB', (500, 700), color).save(data, 'PNG')
        record_id = self.store.save_image(source['id'], base64.b64encode(data.getvalue()).decode())
        local = local or {'gatepass': '', 'ocr_candidates': [], 'barcode_candidates': [],
                          'warnings': ['Test-only unreadable local result'], 'recognition_source': 'local'}
        with self.store.db:
            self.store.db.execute("UPDATE grn_documents SET state='Ready for review',extraction=? WHERE id=?", (json.dumps(local), record_id))
            record = self.store.document(record_id)
            queue_cloud(self.store, record_id, record['image_hash'], record['ocr_revision'])
        return record_id

    def job(self, record_id):
        return self.store.db.execute('SELECT * FROM grn_cloud_jobs WHERE document_id=? ORDER BY id DESC LIMIT 1', (record_id,)).fetchone()

    def test_upload_poll_and_cache_preserve_leading_zeroes(self):
        record_id = self.document()
        with patch('grn_cloud_ocr.requests.post', return_value=response_double(202, **{'Operation-Location': OPERATION})) as post, \
                patch('grn_cloud_ocr.requests.get', return_value=response_double(200, azure_payload_double())):
            self.worker.process_one(self.store)
        record = self.store.document(record_id)
        self.assertEqual(record['gatepass'], '000123')
        self.assertEqual(record['state'], 'Ready for review')
        self.assertIn('Azure', record['extraction']['recognition_source'])
        self.assertEqual(usage_today(self.store), 1)
        self.assertEqual(post.call_count, 1)
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertIn('base64Source', post.call_args.kwargs['json'])
        self.store.retry(record_id)
        record = self.store.document(record_id)
        with self.store.db:
            queue_cloud(self.store, record_id, record['image_hash'], record['ocr_revision'])
        with patch('grn_cloud_ocr.requests.post') as post:
            self.worker.process_one(self.store)
            post.assert_not_called()
        self.assertEqual(self.store.document(record_id)['gatepass'], '000123')
        self.assertEqual(usage_today(self.store), 1)

    def test_local_worker_queues_an_unreadable_photo_without_uploading(self):
        record_id = self.document()
        self.store.retry(record_id)
        stop = threading.Event()
        worker = GRNExtractionWorker(self.store.path, stop)
        # Test-only OCR boundary double: this checks orchestration, not accuracy.
        result = {'gatepass': '', 'warnings': ['Test-only unreadable result']}
        try:
            with patch('grn_ocr.extract_gatepass', return_value=result), patch('grn_cloud_ocr.requests.post') as post:
                worker.thread.start()
                deadline = time.monotonic()+3
                while time.monotonic() < deadline:
                    if self.store.document(record_id)['state'] == 'Cloud queued':
                        break
                    time.sleep(.02)
                self.assertEqual(self.store.document(record_id)['state'], 'Cloud queued')
                self.assertEqual(self.job(record_id)['revision'], 1)
                post.assert_not_called()
        finally:
            stop.set()
            worker.thread.join(3)
        self.assertFalse(worker.thread.is_alive())

    def test_uncertain_upload_is_not_automatically_repeated_even_after_local_retry(self):
        record_id = self.document()
        with patch('grn_cloud_ocr.requests.post', side_effect=requests.Timeout('Test-only timeout')) as post:
            self.worker.process_one(self.store)
            self.worker.process_one(self.store)
            self.assertEqual(post.call_count, 1)
            self.store.retry(record_id)
            record = self.store.document(record_id)
            with self.store.db:
                queue_cloud(self.store, record_id, record['image_hash'], record['ocr_revision'])
            self.worker.process_one(self.store)
            self.assertEqual(post.call_count, 1)
        self.assertEqual(self.job(record_id)['status'], 'uncertain')
        self.assertEqual(usage_today(self.store), 1)
        retry_cloud(self.store, record_id)
        self.assertEqual(self.job(record_id)['status'], 'queued')

    def test_restart_resumes_accepted_request_without_uploading(self):
        record_id = self.document()
        with self.store.db:
            self.store.db.execute("UPDATE grn_cloud_jobs SET status='polling',operation_url=?,deadline=?", (OPERATION, time.time()+60))
        restarted = GRNCloudWorker(self.store.path, threading.Event())
        with patch('grn_cloud_ocr.requests.post') as post, \
                patch('grn_cloud_ocr.requests.get', return_value=response_double(200, azure_payload_double())):
            restarted.process_one(self.store)
            post.assert_not_called()
        self.assertEqual(self.store.document(record_id)['gatepass'], '000123')

    def test_interrupted_submission_requires_explicit_retry(self):
        record_id = self.document()
        with self.store.db:
            self.store.db.execute("UPDATE grn_cloud_jobs SET status='submitting'")
        stop = threading.Event()
        stop.set()
        GRNCloudWorker(self.store.path, stop).run()
        self.assertEqual(self.job(record_id)['status'], 'uncertain')
        self.assertEqual(self.store.document(record_id)['state'], 'Ready for review')

    def test_daily_limit_prevents_another_upload(self):
        self.store.set_settings(grn_cloud_ocr={'provider': 'azure', 'enabled': True, 'endpoint': ENDPOINT, 'daily_limit': 1})
        self.document()
        second = self.document('gray')
        with patch('grn_cloud_ocr.requests.post', return_value=response_double(202, **{'Operation-Location': OPERATION})) as post, \
                patch('grn_cloud_ocr.requests.get', return_value=response_double(200, azure_payload_double())):
            self.worker.process_one(self.store)
            self.worker.process_one(self.store)
            self.assertEqual(post.call_count, 1)
        self.assertIn('Daily cloud upload limit', self.job(second)['error'])
        self.assertEqual(usage_today(self.store), 1)

    def test_disabled_by_default_and_requires_a_positive_limit(self):
        self.store.set_settings(grn_cloud_ocr={})
        record_id = self.document()
        self.assertFalse(cloud_settings(self.store)['enabled'])
        self.assertIsNone(self.job(record_id))
        self.store.set_settings(grn_cloud_ocr={'enabled': True, 'endpoint': ENDPOINT, 'daily_limit': 0})
        with self.store.db:
            record = self.store.document(record_id)
            self.assertFalse(queue_cloud(self.store, record_id, record['image_hash'], 0))

    def test_cloud_pending_blocks_transfer_before_touching_a_lane(self):
        record_id = self.document()
        with self.assertRaisesRegex(ValueError, 'Wait for extraction'):
            fill_grn_request(self.store, record_id, 'EGDC', '000123', 'Test lane', {})

    def test_poll_timeout_can_resume_without_resubmission(self):
        record_id = self.document()
        with self.store.db:
            self.store.db.execute("UPDATE grn_cloud_jobs SET status='polling',operation_url=?,deadline=?", (OPERATION, time.time()-1))
        with patch('grn_cloud_ocr.requests.post') as post:
            self.worker.process_one(self.store)
            post.assert_not_called()
        self.assertEqual(self.job(record_id)['status'], 'timeout')
        retry_cloud(self.store, record_id)
        self.assertEqual(self.job(record_id)['status'], 'polling')

    def test_late_result_preserves_review_clear_and_recapture(self):
        for change in ('review', 'clear', 'done', 'revision'):
            with self.subTest(change=change):
                record_id = self.document({'review': 'red', 'clear': 'green', 'done': 'purple', 'revision': 'blue'}[change])
                job = dict(self.job(record_id))
                if change == 'review':
                    self.store.save_grn_review(record_id, 'EGDC', '009999')
                elif change in ('clear', 'done'):
                    with self.store.db:
                        self.store.db.execute('UPDATE grn_documents SET hidden_reason=? WHERE id=?', ('cleared' if change == 'clear' else 'done', record_id))
                else:
                    self.store.retry(record_id)
                self.worker.finish(self.store, job, parse_azure_result(azure_payload_double()))
                record = self.store.document(record_id)
                self.assertNotEqual(record['gatepass'], '000123')
                if change == 'review':
                    self.assertEqual(record['gatepass'], '009999')
                    self.assertEqual(record['state'], 'Ready for review')
                elif change in ('clear', 'done'):
                    self.assertEqual(record['hidden_reason'], 'cleared' if change == 'clear' else 'done')
                else:
                    self.assertEqual(record['state'], 'Pending')


class CloudEvidenceTests(unittest.TestCase):
    def test_header_association_conflicts_and_body_rejection(self):
        cloud = parse_azure_result(azure_payload_double())
        self.assertEqual(cloud['azure_candidates'], ['000123'])
        local = {'ocr_candidates': ['999888'], 'barcode_candidates': [], 'warnings': []}
        result = merge_cloud_result(local, cloud)
        self.assertEqual(result['gatepass'], '')
        self.assertIn('disagree', result['warnings'][-1])
        payload = azure_payload_double()
        for word in payload['analyzeResult']['pages'][0]['words']:
            word['polygon'][1::2] = [1000, 1000, 1030, 1030]
        self.assertEqual(parse_azure_result(payload)['azure_candidates'], [])

    def test_rotated_azure_coordinates_are_normalized(self):
        payload = azure_payload_double()
        page = payload['analyzeResult']['pages'][0]
        for word in page['words']:
            polygon = word['polygon']
            word['polygon'] = [value for x, y in zip(polygon[::2], polygon[1::2]) for value in (1400-y, x)]
        page.update(width=1400, height=1000, angle=90)
        self.assertEqual(parse_azure_result(payload)['azure_candidates'], ['000123'])

    def test_unrelated_number_farther_along_the_header_line_is_excluded(self):
        payload = azure_payload_double()
        payload['analyzeResult']['pages'][0]['words'].append(
            {'content': '0771234567', 'confidence': .99, 'polygon': [750, 100, 950, 100, 950, 130, 750, 130]})
        self.assertEqual(parse_azure_result(payload)['azure_candidates'], ['000123'])

    def test_credentials_cannot_follow_operation_urls_to_another_host(self):
        client = AzureReadClient(ENDPOINT, 'test-double-key')
        for url in ('http://example.com', 'https://example.com/analyzeResults/1', ENDPOINT+'/different/path'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.operation_url(url)
        for endpoint in ('http://example.com', 'https://example.com', ENDPOINT+'/path', ENDPOINT+'?key=invalid'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_endpoint(endpoint)

    def test_authentication_and_throttling_errors_are_actionable(self):
        for status, message in ((401, 'key'), (403, 'denied'), (429, 'quota')):
            with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, message):
                AzureReadClient.check_response(response_double(status), 202)


class CloudSettingsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = GRNInboxStore(Path(folder.name) / 'inbox.sqlite3')
        self.addCleanup(self.store.close)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.dialog = GRNOCRSettings(self.root, self.store)

    def test_default_disabled_and_incomplete_setup_cannot_enable_uploads(self):
        self.assertFalse(self.dialog.enabled.get())
        self.dialog.enabled.set(True)
        self.dialog.save()
        self.assertFalse(cloud_settings(self.store)['enabled'])
        self.assertIn('positive daily', self.dialog.status.get())

    def test_old_azure_settings_are_not_reused_or_silently_enabled(self):
        self.store.set_settings(grn_cloud_ocr={'enabled': True, 'endpoint': ENDPOINT, 'daily_limit': 2})
        self.assertFalse(cloud_settings(self.store)['enabled'])
        dialog = GRNOCRSettings(self.root, self.store)
        self.assertEqual(dialog.endpoint.get(), OCR_SPACE_ENDPOINT)
        self.assertFalse(dialog.enabled.get())

    def test_key_only_goes_to_credential_manager_and_is_cleared_from_the_form(self):
        self.dialog.endpoint.set(OCR_SPACE_ENDPOINT)
        self.dialog.limit.set('5')
        self.dialog.key.set('test-only-key')
        self.dialog.enabled.set(True)
        # Credential-boundary doubles; no OS secret is created by this test.
        with patch('grn_ocr_settings.save_credential') as save, \
                patch('grn_ocr_settings.load_credential', return_value='test-only-key'):
            self.dialog.save()
        save.assert_called_once_with(OCR_SPACE_ENDPOINT, 'test-only-key')
        self.assertEqual(self.dialog.key.get(), '')
        self.assertTrue(cloud_settings(self.store)['enabled'])
        self.assertNotIn('test-only-key', repr([tuple(row) for row in self.store.db.execute('SELECT * FROM monitor_settings')]))
        self.assertEqual(cloud_settings(self.store)['daily_limit'], 5)


def ocr_space_payload_double(number='000123'):
    """Minimal OCR.space overlay response test double; no live result or score."""
    return {'OCRExitCode': 1, 'IsErroredOnProcessing': False, 'ParsedResults': [
        {'FileParseExitCode': 1, 'ParsedText': 'GATE PASS: ' + number, 'TextOverlay': {'HasOverlay': True, 'Lines': [
            {'Words': [{'WordText': text, 'Left': x, 'Top': 100, 'Width': width, 'Height': 30}
                       for text, x, width in [('GATE', 100, 70), ('PASS:', 180, 70), (number, 270, 120)]]}]}}]}


class OCRSpaceQueueTests(unittest.TestCase):
    document = CloudQueueTests.document
    job = CloudQueueTests.job

    def setUp(self):
        CloudQueueTests.setUp(self)
        self.store.set_settings(grn_cloud_ocr={'enabled': True, 'endpoint': OCR_SPACE_ENDPOINT, 'daily_limit': 2})

    def test_synchronous_upload_uses_key_header_overlay_and_no_polling(self):
        record_id = self.document()
        with patch('grn_cloud_ocr.requests.post', return_value=response_double(200, ocr_space_payload_double())) as post, \
                patch('grn_cloud_ocr.requests.get') as get:
            self.worker.process_one(self.store)
        get.assert_not_called()
        self.assertEqual(self.store.document(record_id)['gatepass'], '000123')
        self.assertEqual(self.job(record_id)['version'], OCR_SPACE_VERSION)
        self.assertEqual(self.job(record_id)['status'], 'complete')
        args = post.call_args
        self.assertEqual(args.args[0], OCR_SPACE_ENDPOINT)
        self.assertEqual(args.kwargs['headers']['apikey'], 'test-double-key')
        self.assertNotIn('params', args.kwargs)
        self.assertEqual(args.kwargs['data']['isOverlayRequired'], 'true')
        self.assertEqual(args.kwargs['data']['OCREngine'], '2')
        self.assertEqual(args.kwargs['files']['file'][2], 'image/jpeg')
        self.assertLessEqual(len(args.kwargs['files']['file'][1]), 1_000_000)
        self.assertFalse(args.kwargs['allow_redirects'])
        reading = self.store.document(record_id)['extraction']
        self.assertIn('OCR.space', reading['recognition_source'])
        self.assertIsNone(reading['evidence'][0]['confidence'])

    def test_timeout_requires_explicit_retry_and_does_not_repeat_upload(self):
        record_id = self.document()
        with patch('grn_cloud_ocr.requests.post', side_effect=requests.Timeout('Test-only timeout')) as post:
            self.worker.process_one(self.store)
            self.worker.process_one(self.store)
            self.assertEqual(post.call_count, 1)
        self.assertEqual(self.job(record_id)['status'], 'uncertain')
        retry_cloud(self.store, record_id)
        self.assertEqual(self.job(record_id)['status'], 'queued')

    def test_api_error_does_not_become_a_gatepass(self):
        record_id = self.document()
        payload = {'OCRExitCode': 4, 'IsErroredOnProcessing': True, 'ErrorMessage': ['Test-only quota error']}
        with patch('grn_cloud_ocr.requests.post', return_value=response_double(200, payload)):
            self.worker.process_one(self.store)
        self.assertEqual(self.store.document(record_id)['gatepass'], '')
        self.assertIn('API key', self.job(record_id)['error'])

    def test_completed_result_is_cached_without_another_upload(self):
        record_id = self.document()
        with patch('grn_cloud_ocr.requests.post', return_value=response_double(200, ocr_space_payload_double())) as post:
            self.worker.process_one(self.store)
            self.store.retry(record_id)
            record = self.store.document(record_id)
            with self.store.db:
                queue_cloud(self.store, record_id, record['image_hash'], record['ocr_revision'])
            self.worker.process_one(self.store)
            self.assertEqual(post.call_count, 1)
        self.assertEqual(usage_today(self.store), 1)


class OCRSpaceEvidenceTests(unittest.TestCase):
    def test_overlay_is_required_and_conflicting_values_are_preserved(self):
        payload = ocr_space_payload_double()
        cloud = parse_ocr_space_result(payload, (500, 700))
        self.assertEqual(cloud['ocr_space_candidates'], ['000123'])
        result = merge_cloud_result({'ocr_candidates': ['999888'], 'warnings': []}, cloud)
        self.assertEqual(result['gatepass'], '')
        payload['ParsedResults'][0]['TextOverlay'] = None
        with self.assertRaisesRegex(ValueError, 'word positions'):
            parse_ocr_space_result(payload, (500, 700))

    def test_body_number_is_not_a_header(self):
        payload = ocr_space_payload_double()
        for word in payload['ParsedResults'][0]['TextOverlay']['Lines'][0]['Words']:
            word['Top'] = 500
        self.assertEqual(parse_ocr_space_result(payload, (500, 700))['ocr_space_candidates'], [])

    def test_endpoint_is_default_and_secrets_cannot_follow_redirects(self):
        self.assertEqual(validate_endpoint(OCR_SPACE_ENDPOINT), OCR_SPACE_ENDPOINT)
        self.assertEqual(validate_endpoint('https://apipro1.ocr.space/parse/image'), 'https://apipro1.ocr.space/parse/image')
        self.assertNotEqual(credential_target(OCR_SPACE_ENDPOINT), credential_target(ENDPOINT))
        for endpoint in ('https://ocr.space/', 'http://api.ocr.space/parse/image', 'https://ocr.space.example.com/parse/image', OCR_SPACE_ENDPOINT+'?apikey=invalid'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_endpoint(endpoint)


if __name__ == '__main__':
    unittest.main()
