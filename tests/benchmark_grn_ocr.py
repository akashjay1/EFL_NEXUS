"""Compare real, labelled photos with a saved OCR source baseline.

Manifest: [{"image": "path/to/photo.jpg", "expected": "000123", "difficult": true}]
Photographs and generated reports stay outside Git. No cloud uploads occur.
Expected numbers must be independently checked against the original photos.
"""

import argparse
import json
from pathlib import Path
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from grn_ocr import extract_gatepass


def benchmark(manifest, output, baseline=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    readers = {'current': extract_gatepass}
    if baseline:
        module = types.ModuleType('grn_ocr_baseline')
        # The preserved code uses the same installed runtime, not a test double.
        module.__file__ = str(ROOT / 'grn_ocr.py')
        exec(compile(Path(baseline).read_text(encoding='utf-8'), str(baseline), 'exec'), module.__dict__)
        readers = {'baseline': module.extract_gatepass, **readers}
    rows = []
    for index, entry in enumerate(json.loads(Path(manifest).read_text(encoding='utf-8'))):
        expected = entry['expected']
        if not isinstance(expected, str) or not expected.isascii() or not expected.isdigit():
            raise ValueError('Every expected gate pass must be a verified digit string, preserving leading zeroes.')
        for name, reader in readers.items():
            started = time.monotonic()
            try:
                result = reader(entry['image'], output / f'{index}-{name}')
            except Exception as exc:
                result = {'gatepass': '', 'warnings': [type(exc).__name__ + ': ' + str(exc)]}
            row = {'case': index, 'reader': name, 'expected': expected, 'image': entry['image'],
                   'transformed': bool(entry.get('transformed', False)),
                   'difficult': bool(entry.get('difficult', False)), 'seconds': round(time.monotonic()-started, 3), **result}
            row['correct'] = row['gatepass'] == expected
            row['incorrect_suggestion'] = bool(row['gatepass']) and not row['correct']
            rows.append(row)
            print(json.dumps({key: row[key] for key in ('case', 'reader', 'gatepass', 'correct', 'seconds')}), flush=True)
            (output / 'results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    summary = {name: {'cases': len([r for r in rows if r['reader'] == name]),
                      'original_photos': sum(not r['transformed'] for r in rows if r['reader'] == name),
                      'transformed_cases': sum(r['transformed'] for r in rows if r['reader'] == name),
                      'correct': sum(r['correct'] for r in rows if r['reader'] == name),
                      'incorrect_suggestions': sum(r['incorrect_suggestion'] for r in rows if r['reader'] == name),
                      'unresolved': sum(not r['gatepass'] for r in rows if r['reader'] == name)} for name in readers}
    summary['cloud_uploads'] = 0
    summary['accuracy_claim'] = 'This sample comparison is not a population accuracy estimate.'
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return rows, summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest')
    parser.add_argument('output')
    parser.add_argument('--baseline')
    args = parser.parse_args()
    benchmark(args.manifest, args.output, args.baseline)
