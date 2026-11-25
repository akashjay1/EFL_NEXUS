import React, { useState } from 'react';
import { Session, SessionEvent } from '../types';
import { Tabs } from '../components/common/LoadingSpinner';
import { SessionHistoryPage } from './SessionHistoryPage';
import { ActivityEventsPage } from './ActivityEventsPage';

export const SessionsAndActivityPage: React.FC<{ sessions: Session[]; events: SessionEvent[] }> = ({ sessions, events }) => {
  const [tab, setTab] = useState<'sessions' | 'events'>('sessions');
  return (
    <div className="space-y-5">
      <Tabs
        label="Sessions and activity"
        active={tab}
        onChange={(id) => setTab(id as 'sessions' | 'events')}
        tabs={[
          { id: 'sessions', label: 'Session history' },
          { id: 'events', label: 'Event stream' },
        ]}
      />
      {tab === 'sessions' ? <SessionHistoryPage initialSessions={sessions} /> : <ActivityEventsPage events={events} />}
    </div>
  );
};
