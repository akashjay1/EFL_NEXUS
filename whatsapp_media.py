"""Shared photo selectors verified in the existing WebView2 capture evidence.

Do not add speculative selectors: unsupported markup must be reported, not
interpreted as an empty conversation or an original-quality image.
"""

import json

MEDIA_SELECTORS = {
    'rows': '[data-id][data-testid^="conv-msg-"]',
    'thumbnail': '[data-testid="image-thumb"]',
    'quote': '[data-testid="quoted-message"]',
    'viewer': '[data-testid="media-viewer-modal"]',
    'original': '[data-testid="media-image"] img',
}

MEDIA_ADAPTER_JS = 'const nexusMedia = ' + json.dumps(MEDIA_SELECTORS) + r''';
const nexusPhotoThumbs = row => [...row.querySelectorAll(nexusMedia.thumbnail)]
    .filter(el => !el.closest(nexusMedia.quote));
'''
