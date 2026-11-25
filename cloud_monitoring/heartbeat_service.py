"""All monitoring disk, credentials and network work belongs to one daemon worker."""
import json
import logging
import os
from pathlib import Path
import queue
import random
import socket
import sqlite3
import threading
import time
from uuid import UUID, uuid4
from . import security
from .cloud_client import CloudClient, CloudError
from .device_identity import read_identity
from .offline_queue import OfflineQueue, ExpiredHistory
from .operator_identity import identity

HEARTBEAT_INTERVAL = 15
DISCONNECTED_TIMEOUT = 90
IDLE_THRESHOLD = 300


class MonitoringService:
    def __init__(self, config_path, version, interval=HEARTBEAT_INTERVAL):
        self.config_path, self.version, self.interval = config_path, version, max(10, interval)
        self.commands = queue.Queue(maxsize=1000)
        self.stopping = threading.Event()
        self.thread = None
        self.message = 'Cloud monitoring disabled.'
        self.installation_uuid = ''
        self.last_interaction = time.monotonic()
        self.module = 'Dashboard'
        self.journal_path = self.session_id = None
        self.shutdown_writer = None
        self.shutdown_persisted = threading.Event()
        self._reconciliation_jobs = None
        self._jobs_lock = threading.Lock()
        self._jobs_due = 0

    def update_reconciliation_jobs(self, records):
        # UI supplies immutable copies; only the monitoring worker sends requests.
        with self._jobs_lock:
            self._reconciliation_jobs = [dict(record) for record in records]

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='cloud-monitoring', daemon=True)
            self.thread.start()

    def status(self):
        return self.message

    def is_alive(self):
        if self.stopping.is_set():
            return bool(self.shutdown_writer and self.shutdown_writer.is_alive())
        return bool(self.thread and self.thread.is_alive())

    def stop(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        if self.journal_path and self.session_id:
            def persist_close():
                journal = None
                try:
                    journal = OfflineQueue(self.journal_path, timeout=.25)
                    journal.append(self.session_id, 'closed', {})
                    self.shutdown_persisted.set()
                except (OSError, ValueError, sqlite3.Error):
                    self.message = 'Shutdown journal unavailable; next launch must recover an unclean session.'
                finally:
                    if journal:
                        journal.close()
            self.shutdown_writer = threading.Thread(target=persist_close, name='cloud-close-journal', daemon=True)
            self.shutdown_writer.start()

    def interact(self, *_):
        self.last_interaction = time.monotonic()

    def update_context(self, _identity, module):
        # Re-read the validated profile through the active ConfigStore path in the worker.
        self.module = module

    def enroll(self, value):
        self.commands.put_nowait(('enroll', value))

    def _run(self):
        outbox = client = None
        lease = None
        try:
            root = Path(os.environ['LOCALAPPDATA']) / 'EFL_NEXUS' / 'Monitoring'
            root.mkdir(parents=True, exist_ok=True)
            settings = root / 'connection.json'

            try:
                self.installation_uuid = read_identity()
            except Exception as e:
                self.message = f'Machine identity error: {e}'
                logging.getLogger(__name__).warning('Could not read machine identity: %s', e)
                return

            outbox = OfflineQueue(root / 'outbox.sqlite3')
            session = str(uuid4())

            # Windows locks disappear on forced termination; other active launches keep theirs.
            import msvcrt
            lease = (root / (session + '.lock')).open('w+b')
            lease.write(b'1'); lease.flush(); lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)

            # Clean up unclosed sessions from earlier crashes
            for old, in outbox.db.execute('select id from launches where ended=0').fetchall():
                lock_path = root / (old + '.lock')
                try:
                    with lock_path.open('a+b') as old_lock:
                        old_lock.seek(0)
                        try:
                            msvcrt.locking(old_lock.fileno(), msvcrt.LK_NBLCK, 1)
                        except OSError:
                            continue
                        outbox.append(old, 'unclean', {})
                        old_lock.seek(0)
                        msvcrt.locking(old_lock.fileno(), msvcrt.LK_UNLCK, 1)
                    try:
                        lock_path.unlink()
                    except OSError:
                        pass
                except OSError:
                    continue

            # Load machine DPAPI credential or fallback to user settings
            machine_cred = security.load_machine_credential()
            if not machine_cred:
                from .device_identity import auto_register_machine
                if auto_register_machine():
                    machine_cred = security.load_machine_credential()

            if machine_cred:
                connection = {
                    'url': machine_cred['url'],
                    'key': machine_cred['key'],
                    'credential_id': machine_cred['credential_id'],
                    'secret': machine_cred['secret'],
                    'device_id': machine_cred.get('device_id'),
                    'pending': False
                }
            elif settings.exists():
                try:
                    connection = json.loads(settings.read_text(encoding='utf-8'))
                except Exception:
                    connection = None
            else:
                connection = None

            if not connection:
                self.message = 'Cloud monitoring waiting for machine provisioning.'

            active = False
            previous = None
            failures, due = 0, 0
            rejected = False

            while True:
                if self.stopping.is_set():
                    break

                try:
                    command, value = self.commands.get_nowait()
                except queue.Empty:
                    command = None

                if command == 'enroll':
                    if active and not rejected:
                        self.message = 'Restart EFL NEXUS before replacing an active enrollment.'
                    else:
                        try:
                            data = json.loads(value)
                            if set(data) != {'url', 'key', 'enrollment_id', 'code', 'installation_uuid'}:
                                raise ValueError('Invalid enrollment fields')
                            if str(UUID(data['installation_uuid'])) != self.installation_uuid:
                                raise ValueError('Wrong installation')
                            if len(data['code']) != 64 or any(c not in '0123456789abcdef' for c in data['code'].lower()):
                                raise ValueError('Invalid enrollment code')

                            candidate = CloudClient(data['url'], data['key'])
                            record = security.pending({k: data[k] for k in ('enrollment_id', 'code', 'installation_uuid')})
                            try:
                                security.save_machine_credential({
                                    **record, 'url': candidate.url, 'key': candidate.key
                                })
                                security.set_machine_active(True)
                                machine_cred = security.load_machine_credential()
                            except Exception:
                                security.save(candidate.url, record)

                            new_connection = {
                                'url': candidate.url,
                                'key': candidate.key,
                                'credential_id': record['credential_id'],
                                'secret': record.get('secret'),
                                'pending': True
                            }
                            temporary = settings.with_suffix('.tmp')
                            temporary.write_text(json.dumps(new_connection), encoding='utf-8')
                            os.replace(temporary, settings)
                            connection = new_connection
                            if client:
                                client.close()
                                client = None
                            candidate.close()
                            rejected, due = False, 0
                        except Exception:
                            self.message = 'Enrollment could not be saved. Check shared identity and enrollment details.'

                # Check if machine credential became available dynamically
                if not connection and not rejected:
                    machine_cred = security.load_machine_credential()
                    if not machine_cred:
                        from .device_identity import auto_register_machine
                        try:
                            if auto_register_machine():
                                machine_cred = security.load_machine_credential()
                        except Exception as e:
                            logging.getLogger(__name__).debug('Auto-registration on start: %s', e)
                    if machine_cred:
                        connection = {
                            'url': machine_cred['url'],
                            'key': machine_cred['key'],
                            'credential_id': machine_cred['credential_id'],
                            'secret': machine_cred['secret'],
                            'device_id': machine_cred.get('device_id'),
                            'pending': False
                        }
                        self.message = 'Cloud monitoring provisioned.'

                if connection and not rejected:
                    if client is None:
                        client = CloudClient(connection['url'], connection['key'])
                    if time.monotonic() >= due:
                        try:
                            if machine_cred:
                                credential = machine_cred
                            elif connection.get('secret'):
                                credential = connection
                            else:
                                credential = security.load(connection['url'], connection['credential_id'])

                            if connection.get('pending'):
                                enroll_res = client.post('device-enroll', credential)
                                connection['pending'] = False
                                if 'device_id' in enroll_res:
                                    connection['device_id'] = enroll_res['device_id']
                                    if machine_cred:
                                        machine_cred['device_id'] = enroll_res['device_id']
                                        try:
                                            security.save_machine_credential(machine_cred)
                                            security.set_machine_active(True)
                                        except Exception:
                                            pass
                                temporary = settings.with_suffix('.tmp')
                                temporary.write_text(json.dumps(connection), encoding='utf-8')
                                os.replace(temporary, settings)

                            if not active:
                                current = identity(self.config_path, socket.gethostname())
                                outbox.create(session, connection['credential_id'], {
                                    **current,
                                    'device_name': socket.gethostname(),
                                    'module': self.module,
                                    'app_version': self.version
                                })
                                self.journal_path, self.session_id = root / 'outbox.sqlite3', session
                                previous = (current, self.module)
                                active = True

                            outbox.report_gap(session)

                            # Replay persisted sessions, always with their original account credential.
                            for sid, cid in outbox.db.execute('select id,credential from launches where blocked=0').fetchall():
                                try:
                                    batch = outbox.batch(sid)
                                except ExpiredHistory:
                                    outbox.archive_expired(sid)
                                    if sid == session:
                                        session = str(uuid4())
                                        current = identity(self.config_path, socket.gethostname())
                                        outbox.create(session, connection['credential_id'], {
                                            **current,
                                            'device_name': socket.gethostname(),
                                            'module': self.module,
                                            'app_version': self.version
                                        })
                                        self.session_id = session
                                        previous = (current, self.module)
                                    outbox.report_gap(session)
                                    continue

                                if not batch and sid != session:
                                    continue

                                try:
                                    if machine_cred and machine_cred['credential_id'] == cid:
                                        cred = machine_cred
                                    elif connection.get('credential_id') == cid and connection.get('secret'):
                                        cred = connection
                                    else:
                                        cred = security.load(connection['url'], cid)

                                    live = outbox.live(sid, time.monotonic() - self.last_interaction) if sid == session and not self.stopping.is_set() else None
                                    result = client.post('device-telemetry', {'session_id': sid, 'events': batch, 'live': live}, cred)
                                    outbox.acknowledge(sid, result['event_sequence'])
                                except CloudError as historical_error:
                                    if sid != session and historical_error.status in (400, 401, 403, 409):
                                        with outbox.db:
                                            outbox.db.execute('update launches set blocked=1 where id=?', (sid,))
                                        continue
                                    raise

                            failures = 0
                            # This independent feed must never break session telemetry or
                            # trigger credential revocation handling on a failed jobs request.
                            if time.monotonic() >= self._jobs_due:
                                with self._jobs_lock:
                                    jobs = self._reconciliation_jobs
                                if jobs is not None:
                                    try:
                                        for offset in range(0, len(jobs), 50):
                                            client.post('device-jobs', {'jobs': jobs[offset:offset + 50]}, credential)
                                    except Exception as exc:
                                        logging.getLogger(__name__).warning('Reconciliation sync failed (%s)', type(exc).__name__)
                                self._jobs_due = time.monotonic() + 30
                            blocked = outbox.db.execute('select count(*) from launches where blocked=1').fetchone()[0]
                            self.message = 'Cloud connected.' if not blocked else 'Cloud connected; historical sessions need review.'
                            due = time.monotonic() + self.interval
                        except CloudError as error:
                            if error.status == 403:
                                rejected = True
                                self.message = 'Device authorization revoked by administrator.'
                                logging.getLogger(__name__).critical('Device rejected with HTTP 403 (revocation detected). Initiating decommission self-destruct.')
                                from .decommission import trigger_self_destruct
                                trigger_self_destruct(reason='Device revoked by administrator')
                                break
                            elif error.status == 401:
                                # Stale or purged credential: clear invalid credential and attempt auto-registration
                                logging.getLogger(__name__).info('Credential rejected (HTTP 401). Attempting fresh zero-touch auto-registration.')
                                from .device_identity import auto_register_machine
                                security.delete_machine_credential()
                                if auto_register_machine(force=True):
                                    machine_cred = security.load_machine_credential()
                                    if machine_cred:
                                        connection = {
                                            'url': machine_cred['url'],
                                            'key': machine_cred['key'],
                                            'credential_id': machine_cred['credential_id'],
                                            'secret': machine_cred['secret'],
                                            'device_id': machine_cred.get('device_id'),
                                            'pending': False
                                        }
                                        if client:
                                            client.close()
                                            client = None
                                        failures = 0
                                        due = time.monotonic()
                                        continue
                                rejected = True
                                if active:
                                    outbox.append(session, 'unclean', {})
                                    with outbox.db:
                                        outbox.db.execute('update launches set blocked=1 where id=?', (session,))
                                    active = False
                                    session = str(uuid4())
                                self.message = 'Cloud credential invalid or expired.'
                            elif error.status in (400, 409):
                                rejected = True
                                if active:
                                    outbox.append(session, 'unclean', {})
                                    with outbox.db:
                                        outbox.db.execute('update launches set blocked=1 where id=?', (session,))
                                    active = False
                                    session = str(uuid4())
                                self.message = 'Cloud needs attention: check credentials, clock and pending history. History retained.'
                            else:
                                failures += 1
                        except Exception:
                            failures += 1

                        if failures:
                            self.message = 'Cloud unavailable; events retained locally.'
                            due = time.monotonic() + min(240, 2 ** min(failures, 7)) * random.uniform(.8, 1.2)

                if active:
                    current = identity(self.config_path, socket.gethostname())
                    if current != previous[0]:
                        outbox.append(session, 'operator_changed', current)
                    if self.module != previous[1]:
                        outbox.append(session, 'module_changed', {'module': self.module})
                    previous = (current, self.module)

                if self.stopping.is_set():
                    if active:
                        outbox.append(session, 'closed', {})
                        if client and not rejected:
                            try:
                                result = client.post('device-telemetry', {
                                    'session_id': session,
                                    'events': outbox.batch(session),
                                    'live': None
                                }, credential)
                                outbox.acknowledge(session, result['event_sequence'])
                            except Exception:
                                pass  # Durable close remains for the next launch.
                    break

                self.stopping.wait(.5)
        except Exception as error:
            logging.getLogger(__name__).error('Monitoring initialization failed (%s)', type(error).__name__)
            self.message = 'Cloud monitoring unavailable. Shared device setup may be required; the application remains available.'
        finally:
            if client:
                client.close()
            if outbox:
                outbox.close()
            if lease:
                try:
                    import msvcrt
                    lease.seek(0)
                    msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
                lease.close()
                try:
                    (root / (session + '.lock')).unlink()
                except (OSError, UnboundLocalError):
                    pass
