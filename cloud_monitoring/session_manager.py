from datetime import datetime, timezone
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def event(sequence, kind, payload, timestamp=None):
    return {'id': str(uuid4()), 'sequence': sequence, 'type': kind,
            'timestamp': timestamp or utc_now(), 'payload': payload}
