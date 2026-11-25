"""Worker-owned transactional outbox. Overflow is counted, never punched into sequences."""
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone, timedelta
from .session_manager import event, utc_now


class ExpiredHistory(ValueError):
    """Never send events the deployed backend will reject or silently renumber them."""


class OfflineQueue:
    def __init__(self, path, limit=10000, timeout=2):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=timeout)
        self.limit = limit
        self.db.executescript('''
          pragma journal_mode=WAL;
          pragma synchronous=FULL;
          create table if not exists launches(id text primary key, credential text not null,
            next_sequence integer not null default 1, ack integer not null default 0,
            live_sequence integer not null default 0, ended integer not null default 0,
            dropped integer not null default 0, last_stamp text not null, blocked integer not null default 0);
          create table if not exists outbox(session text not null references launches(id),
            sequence integer not null, body text not null, primary key(session,sequence));
          create table if not exists expired_history(session text,sequence integer,body text,
            primary key(session,sequence));
          create table if not exists pending_gaps(id integer primary key check(id=1), count integer not null);
          insert or ignore into pending_gaps values(1,0);
        ''')

    def create(self, session, credential, payload):
        with self.db:
            count = self.db.execute('select count(*) from outbox').fetchone()[0]
            opened = self.db.execute('select count(*) from launches where ended=0').fetchone()[0]
            if count + opened * 2 + 3 > self.limit:
                raise ValueError('Outbox capacity reserved for existing session shutdowns.')
            self.db.execute('insert into launches(id,credential,last_stamp) values(?,?,?)', (session, credential, utc_now()))
            self._append(session, 'started', payload)

    def _append(self, session, kind, payload):
        seq, stamp = self.db.execute('select next_sequence,last_stamp from launches where id=?', (session,)).fetchone()
        stamp = max(stamp, utc_now())
        body = event(seq, kind, payload, stamp)
        self.db.execute('insert into outbox values(?,?,?)', (session, seq, json.dumps(body)))
        self.db.execute('update launches set next_sequence=?,last_stamp=?,ended=? where id=?',
                        (seq + 1, stamp, int(kind in ('closed', 'unclean')), session))

    def append(self, session, kind, payload):
        with self.db:
            state = self.db.execute('select ended,dropped from launches where id=?', (session,)).fetchone()
            if state[0]:
                return False
            if kind in ('closed', 'unclean'):
                if state[1]:
                    self._append(session, 'recording_gap', {'dropped_events': state[1]})
                    self.db.execute('update launches set dropped=0 where id=?', (session,))
                self._append(session, kind, payload)
                return True
            count = self.db.execute('select count(*) from outbox').fetchone()[0]
            opened = self.db.execute('select count(*) from launches where ended=0').fetchone()[0]
            if count + opened * 2 >= self.limit:
                self.db.execute('update launches set dropped=dropped+1 where id=?', (session,))
                return False
            self._append(session, kind, payload)
            return True

    def batch(self, session):
        events = [json.loads(r[0]) for r in self.db.execute(
            'select body from outbox where session=? order by sequence limit 25', (session,))]
        if any(datetime.fromisoformat(e['timestamp'].replace('Z', '+00:00')) <
               datetime.now(timezone.utc) - timedelta(days=7) for e in events):
            self.archive_expired(session)
            raise ExpiredHistory('Seven-day history limit exceeded; history retained for review.')
        return events

    def acknowledge(self, session, high):
        with self.db:
            ack, next_seq = self.db.execute('select ack,next_sequence from launches where id=?', (session,)).fetchone()
            if not isinstance(high, int) or not ack <= high < next_seq:
                raise ValueError('Invalid server sequence; history retained.')
            self.db.execute('delete from outbox where session=? and sequence<=?', (session, high))
            self.db.execute('update launches set ack=? where id=?', (high, session))
            dropped, ended = self.db.execute('select dropped,ended from launches where id=?', (session,)).fetchone()
            opened = self.db.execute('select count(*) from launches where ended=0').fetchone()[0]
            if dropped and not ended and self.db.execute('select count(*) from outbox').fetchone()[0] + opened * 2 < self.limit:
                self._append(session, 'recording_gap', {'dropped_events': dropped})
                self.db.execute('update launches set dropped=0 where id=?', (session,))

    def archive_expired(self, session):
        """Preserve original IDs/sequences for review, never replay an invented old start."""
        with self.db:
            count = self.db.execute('select count(*) from outbox where session=?', (session,)).fetchone()[0]
            self.db.execute('insert or ignore into expired_history select session,sequence,body from outbox where session=?', (session,))
            self.db.execute('delete from outbox where session=?', (session,))
            dropped = self.db.execute('select dropped from launches where id=?', (session,)).fetchone()[0]
            self.db.execute('update launches set ended=1,blocked=1,dropped=0 where id=?', (session,))
            self.db.execute('update pending_gaps set count=count+? where id=1', (count+dropped,))
        return count+dropped

    def report_gap(self, session):
        with self.db:
            count = self.db.execute('select count from pending_gaps where id=1').fetchone()[0]
            if count:
                occupied = self.db.execute('select count(*) from outbox').fetchone()[0]
                opened = self.db.execute('select count(*) from launches where ended=0').fetchone()[0]
                if occupied + opened*2 >= self.limit:
                    return False
                self._append(session, 'recording_gap', {'dropped_events': count})
                self.db.execute('update pending_gaps set count=0 where id=1')
        return True

    def live(self, session, idle):
        with self.db:
            self.db.execute('update launches set live_sequence=live_sequence+1 where id=?', (session,))
            seq = self.db.execute('select live_sequence from launches where id=?', (session,)).fetchone()[0]
        return {'sequence': seq, 'sent_at': utc_now(), 'idle_seconds': min(604800, int(idle))}

    def close(self):
        self.db.close()
