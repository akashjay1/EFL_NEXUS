import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const USER_DATA_DIR = 'C:\\Users\\Akash\\AppData\\Local\\Temp\\chrome_cdp_profile_' + Date.now();
const SCREENSHOTS_DIR = 'X:\\EFL_NEXUS\\cloud_tracking\\dashboard\\screenshots';
const ARTIFACT_DIR = 'C:\\Users\\Akash\\.gemini\\antigravity\\brain\\3a8d7f54-d6a7-44c9-8810-d9833a346fdc';

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.id = 1;
    this.callbacks = new Map();
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.onopen = () => resolve();
      this.ws.onerror = (err) => reject(err);
      this.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.method === 'Runtime.consoleAPICalled') {
          console.log('[BROWSER CONSOLE]', msg.params.type, msg.params.args.map((a) => a.value ?? a.description ?? '').join(' '));
        }
        if (msg.id && this.callbacks.has(msg.id)) {
          const { resolve, reject } = this.callbacks.get(msg.id);
          this.callbacks.delete(msg.id);
          if (msg.error) {
            reject(new Error(msg.error.message));
          } else {
            resolve(msg.result);
          }
        }
      };
    });
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const msgId = this.id++;
      this.callbacks.set(msgId, { resolve, reject });
      this.ws.send(JSON.stringify({ id: msgId, method, params }));
    });
  }

  close() {
    if (this.ws) {
      this.ws.close();
    }
  }
}

// Valid base64url encoded JWT payload with AAL2
const mockJwtPayload = Buffer.from(
  JSON.stringify({
    sub: '86ebfb91-952b-4057-afa1-fa4a83106f8e',
    aud: 'authenticated',
    role: 'authenticated',
    email: 'admin.lead@eflnexus.internal',
    aal: 'aal2',
    exp: 1893456000,
  })
).toString('base64url');

const mockJwt = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.${mockJwtPayload}.mock_valid_signature`;

async function main() {
  console.log('Spawning headless Chrome...');
  const chromeProcess = spawn(
    CHROME_PATH,
    [
      '--headless=new',
      '--remote-debugging-port=9222',
      `--user-data-dir=${USER_DATA_DIR}`,
      '--disable-gpu',
      '--no-first-run',
      '--hide-scrollbars',
      'about:blank',
    ],
    { stdio: 'ignore' }
  );

  let connected = false;
  let attempts = 0;
  while (!connected && attempts < 25) {
    try {
      attempts++;
      const res = await fetch('http://localhost:9222/json/version');
      if (res.ok) {
        connected = true;
      }
    } catch {
      await sleep(250);
    }
  }

  if (!connected) {
    chromeProcess.kill();
    throw new Error('Failed to connect to Chrome CDP endpoint.');
  }

  console.log('Connected to Chrome CDP!');

  const targetsRes = await fetch('http://localhost:9222/json/list');
  const targets = await targetsRes.json();
  const pageTarget = targets.find((t) => t.type === 'page') || targets[0];
  const cdp = new CDPClient(pageTarget.webSocketDebuggerUrl);
  await cdp.connect();

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  async function setViewport(width, height, isMobile = false) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: isMobile,
    });
  }

  async function takeScreenshot(name) {
    const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
    const localPath = path.join(SCREENSHOTS_DIR, name);
    const artifactPath = path.join(ARTIFACT_DIR, name);
    const buffer = Buffer.from(data, 'base64');
    fs.writeFileSync(localPath, buffer);
    fs.writeFileSync(artifactPath, buffer);
    console.log(`Saved screenshot: ${name} (${buffer.length} bytes)`);
  }

  // 1. Unauthenticated Login Screenshots
  console.log('Capturing Login page screenshots...');
  await setViewport(1440, 900);
  await cdp.send('Page.navigate', { url: 'http://localhost:4173/' });
  await sleep(1500);
  await takeScreenshot('01_login_desktop.png');

  await setViewport(768, 1024);
  await sleep(400);
  await takeScreenshot('01_login_tablet.png');

  await setViewport(375, 812, true);
  await sleep(400);
  await takeScreenshot('01_login_mobile.png');

  // 2. Inject Mock Auth and API Interceptor for Authenticated Session
  console.log('Injecting authenticated administrator session & Supabase interceptor...');
  const mockInjectionCode = `
    (() => {
      const mockSession = {
        access_token: '${mockJwt}',
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: 1893456000,
        refresh_token: 'mock-refresh-token',
        user: {
          id: '86ebfb91-952b-4057-afa1-fa4a83106f8e',
          aud: 'authenticated',
          role: 'authenticated',
          email: 'admin.lead@eflnexus.internal',
          created_at: '2026-11-01T10:00:00Z',
          confirmed_at: '2026-11-01T10:05:00Z',
          app_metadata: { provider: 'email', providers: ['email'] },
          user_metadata: { full_name: 'Lead Administrator' }
        }
      };

      if (window.location.origin === 'http://localhost:4173') {
        try {
          window.localStorage.setItem('efl_nexus_admin_session', JSON.stringify(mockSession));
          window.localStorage.setItem('efl_nexus_timezone', 'Asia/Colombo');
        } catch (e) {
          console.error('Storage error:', e);
        }
      }

      const originalFetch = window.fetch;
      window.fetch = async function(input, init) {
        const url = typeof input === 'string' ? input : (input && input.url ? input.url : '');

        // 1. Auth Factors
        if (url.includes('/auth/v1/factors')) {
          return new Response(JSON.stringify({
            all: [{ id: 'totp-factor-1', friendly_name: 'Lead TOTP Authenticator', factor_type: 'totp', status: 'verified', created_at: '2026-11-01T10:00:00Z' }],
            totp: [{ id: 'totp-factor-1', friendly_name: 'Lead TOTP Authenticator', factor_type: 'totp', status: 'verified', created_at: '2026-11-01T10:00:00Z' }]
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }

        // 2. Auth User
        if (url.includes('/auth/v1/user')) {
          return new Response(JSON.stringify({
            ...mockSession.user,
            factors: [{ id: 'totp-factor-1', factor_type: 'totp', status: 'verified' }]
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }

        // 3. Admin profiles table
        if (url.includes('/rest/v1/admin_profiles')) {
          const profile = {
            user_id: '86ebfb91-952b-4057-afa1-fa4a83106f8e',
            role: 'owner',
            slot: 1,
            created_at: '2026-11-01T10:00:00Z',
            revoked_at: null
          };
          const acceptHeader = init?.headers ? (init.headers.Accept || init.headers.accept) : '';
          const responseBody = acceptHeader && acceptHeader.includes('vnd.pgrst.object+json')
            ? JSON.stringify(profile)
            : JSON.stringify([profile]);

          return new Response(responseBody, {
            status: 200,
            headers: { 'Content-Type': 'application/json', 'Content-Range': '0-0/1' }
          });
        }

        // 4. Monitoring Settings
        if (url.includes('/rest/v1/monitoring_settings')) {
          const settings = {
            id: true,
            heartbeat_seconds: 15,
            disconnected_seconds: 45,
            idle_seconds: 300,
            dashboard_refresh_seconds: 15,
            history_days: 30
          };
          return new Response(JSON.stringify([settings]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          });
        }

        // 5. Snapshot RPC
        if (url.includes('/rest/v1/rpc/nexus_current_snapshot')) {
          return new Response(JSON.stringify({
            server_time: new Date().toISOString(),
            settings: {
              id: true,
              heartbeat_seconds: 15,
              disconnected_seconds: 45,
              idle_seconds: 300,
              dashboard_refresh_seconds: 15,
              history_days: 30
            },
            devices: [
              {
                id: 'd1111111-1111-1111-1111-111111111111',
                installation_uuid: '7b8e5c1a-2d3f-4a5b-9c8d-1e2f3a4b5c6d',
                device_name: 'OFFICE-PC-01',
                created_at: new Date(Date.now() - 86400000 * 5).toISOString(),
                revoked_at: null
              },
              {
                id: 'd2222222-2222-2222-2222-222222222222',
                installation_uuid: '8c9f6d2b-3e4a-5b6c-0d9e-2f3a4b5c6d7e',
                device_name: 'DISPATCH-WORKSTATION-02',
                created_at: new Date(Date.now() - 86400000 * 3).toISOString(),
                revoked_at: null
              },
              {
                id: 'd3333333-3333-3333-3333-333333333333',
                installation_uuid: '9d0a7e3c-4f5b-6c7d-1e0f-3a4b5c6d7e8f',
                device_name: 'QA-LAB-DESK-03',
                created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
                revoked_at: null
              },
              {
                id: 'd4444444-4444-4444-4444-444444444444',
                installation_uuid: '0e1b8f4d-5a6c-7d8e-2f1a-4b5c6d7e8f90',
                device_name: 'WAREHOUSE-HANDHELD-04',
                created_at: new Date(Date.now() - 86400000 * 10).toISOString(),
                revoked_at: new Date(Date.now() - 86400000 * 1).toISOString()
              }
            ],
            sessions: [
              {
                id: 's1111111-1111-1111-1111-111111111111',
                device_id: 'd1111111-1111-1111-1111-111111111111',
                device_name_snapshot: 'OFFICE-PC-01',
                operator_name: 'Nuwan Perera',
                identity_source: 'KPI Profile',
                app_version: '5.2.0-win-x64',
                active_module: 'GRN Inspection & Verification',
                started_at: new Date(Date.now() - 3600000 * 2).toISOString(),
                last_seen_at: new Date(Date.now() - 12000).toISOString(),
                idle_seconds: 12,
                status: 'online'
              },
              {
                id: 's2222222-2222-2222-2222-222222222222',
                device_id: 'd2222222-2222-2222-2222-222222222222',
                device_name_snapshot: 'DISPATCH-WORKSTATION-02',
                operator_name: 'Kamal Silva',
                identity_source: 'KPI Profile',
                app_version: '5.2.0-win-x64',
                active_module: 'GDN Dispatch Consolidation',
                started_at: new Date(Date.now() - 3600000 * 5).toISOString(),
                last_seen_at: new Date(Date.now() - 420000).toISOString(),
                idle_seconds: 420,
                status: 'idle'
              },
              {
                id: 's3333333-3333-3333-3333-333333333333',
                device_id: 'd3333333-3333-3333-3333-333333333333',
                device_name_snapshot: 'QA-LAB-DESK-03',
                operator_name: 'QA-LAB-DESK-03',
                identity_source: 'Device Fallback',
                app_version: '5.2.0-win-x64',
                active_module: 'Batch Quality Analysis',
                started_at: new Date(Date.now() - 3600000 * 8).toISOString(),
                last_seen_at: new Date(Date.now() - 1800000).toISOString(),
                idle_seconds: 1800,
                status: 'disconnected'
              }
            ]
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }

        // 6. Session Events
        if (url.includes('/rest/v1/session_events')) {
          const events = [
            {
              id: 'e1',
              session_id: 's1111111-1111-1111-1111-111111111111',
              sequence: 1,
              event_type: 'started',
              event_timestamp: new Date(Date.now() - 3600000 * 2).toISOString(),
              received_at: new Date(Date.now() - 3600000 * 2).toISOString(),
              metadata: { client_os: 'Windows 10 Pro', version: '5.2.0' }
            },
            {
              id: 'e2',
              session_id: 's1111111-1111-1111-1111-111111111111',
              sequence: 2,
              event_type: 'operator_changed',
              event_timestamp: new Date(Date.now() - 3600000 * 1.8).toISOString(),
              received_at: new Date(Date.now() - 3600000 * 1.8).toISOString(),
              metadata: { operator_name: 'Nuwan Perera', source: 'KPI Profile' }
            },
            {
              id: 'e3',
              session_id: 's1111111-1111-1111-1111-111111111111',
              sequence: 3,
              event_type: 'module_changed',
              event_timestamp: new Date(Date.now() - 3600000 * 1.5).toISOString(),
              received_at: new Date(Date.now() - 3600000 * 1.5).toISOString(),
              metadata: { module: 'GRN Inspection & Verification' }
            },
            {
              id: 'e4',
              session_id: 's1111111-1111-1111-1111-111111111111',
              sequence: 4,
              event_type: 'recording_gap',
              event_timestamp: new Date(Date.now() - 3600000 * 0.5).toISOString(),
              received_at: new Date(Date.now() - 3600000 * 0.5).toISOString(),
              metadata: { gap_duration_seconds: 48, buffered_events: 14 }
            },
            {
              id: 'e5',
              session_id: 's2222222-2222-2222-2222-222222222222',
              sequence: 1,
              event_type: 'started',
              event_timestamp: new Date(Date.now() - 3600000 * 5).toISOString(),
              received_at: new Date(Date.now() - 3600000 * 5).toISOString(),
              metadata: { operator_name: 'Kamal Silva', source: 'KPI Profile' }
            }
          ];
          return new Response(JSON.stringify(events), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          });
        }

        // 7. Sessions table query
        if (url.includes('/rest/v1/sessions')) {
          const sessions = [
            {
              id: 's1111111-1111-1111-1111-111111111111',
              device_id: 'd1111111-1111-1111-1111-111111111111',
              credential_id: 'c1111111-1111-1111-1111-111111111111',
              device_name_snapshot: 'OFFICE-PC-01',
              operator_name_snapshot: 'Nuwan Perera',
              identity_source: 'KPI Profile',
              app_version: '5.2.0-win-x64',
              active_module: 'GRN Inspection & Verification',
              started_at: new Date(Date.now() - 3600000 * 2).toISOString(),
              received_at: new Date(Date.now() - 3600000 * 2).toISOString(),
              last_event_at: new Date(Date.now() - 12000).toISOString(),
              last_seen_at: new Date(Date.now() - 12000).toISOString(),
              idle_seconds: 12,
              ended_at: null,
              end_reason: null,
              end_is_estimated: false,
              event_sequence: 142,
              live_sequence: 142,
              disconnected_at: null
            },
            {
              id: 's2222222-2222-2222-2222-222222222222',
              device_id: 'd2222222-2222-2222-2222-222222222222',
              credential_id: 'c2222222-2222-2222-2222-222222222222',
              device_name_snapshot: 'DISPATCH-WORKSTATION-02',
              operator_name_snapshot: 'Kamal Silva',
              identity_source: 'KPI Profile',
              app_version: '5.2.0-win-x64',
              active_module: 'GDN Dispatch Consolidation',
              started_at: new Date(Date.now() - 3600000 * 5).toISOString(),
              received_at: new Date(Date.now() - 3600000 * 5).toISOString(),
              last_event_at: new Date(Date.now() - 420000).toISOString(),
              last_seen_at: new Date(Date.now() - 420000).toISOString(),
              idle_seconds: 420,
              ended_at: null,
              end_reason: null,
              end_is_estimated: false,
              event_sequence: 310,
              live_sequence: 310,
              disconnected_at: null
            },
            {
              id: 's3333333-3333-3333-3333-333333333333',
              device_id: 'd3333333-3333-3333-3333-333333333333',
              credential_id: 'c3333333-3333-3333-3333-333333333333',
              device_name_snapshot: 'QA-LAB-DESK-03',
              operator_name_snapshot: 'QA-LAB-DESK-03',
              identity_source: 'Device Fallback',
              app_version: '5.2.0-win-x64',
              active_module: 'Batch Quality Analysis',
              started_at: new Date(Date.now() - 3600000 * 8).toISOString(),
              received_at: new Date(Date.now() - 3600000 * 8).toISOString(),
              last_event_at: new Date(Date.now() - 1800000).toISOString(),
              last_seen_at: new Date(Date.now() - 1800000).toISOString(),
              idle_seconds: 1800,
              ended_at: null,
              end_reason: null,
              end_is_estimated: false,
              event_sequence: 85,
              live_sequence: 85,
              disconnected_at: new Date(Date.now() - 1750000).toISOString()
            }
          ];
          return new Response(JSON.stringify(sessions), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          });
        }

        // 8. Edge Function admin-control
        if (url.includes('/functions/v1/admin-control')) {
          return new Response(JSON.stringify({
            result: {
              admins: [
                {
                  user_id: '86ebfb91-952b-4057-afa1-fa4a83106f8e',
                  email: 'admin.lead@eflnexus.internal',
                  role: 'owner',
                  slot: 1,
                  created_at: '2026-11-01T10:00:00Z',
                  revoked_at: null
                },
                {
                  user_id: 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d',
                  email: 'supervisor.ops@eflnexus.internal',
                  role: 'admin',
                  slot: 2,
                  created_at: '2026-11-02T08:30:00Z',
                  revoked_at: null
                }
              ],
              invitations: [
                {
                  id: 'inv-001',
                  email: 'auditor.colombo@eflnexus.internal',
                  role: 'admin',
                  slot: 3,
                  created_at: '2026-11-02T14:15:00Z'
                }
              ]
            }
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }

        return originalFetch.apply(this, arguments);
      };
    })();
  `;

  await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
    source: mockInjectionCode,
  });

  const pages = [
    { hash: 'overview', name: '02_overview' },
    { hash: 'operators', name: '03_operators' },
    { hash: 'devices', name: '04_devices' },
    { hash: 'sessions', name: '05_sessions' },
    { hash: 'events', name: '06_events' },
    { hash: 'admins', name: '07_admins' },
    { hash: 'mfa', name: '08_mfa' },
    { hash: 'settings', name: '09_settings' },
  ];

  // Capture all 8 pages on Desktop (1440x900)
  console.log('Capturing Desktop pages (1440x900)...');
  await setViewport(1440, 900);

  for (const p of pages) {
    await cdp.send('Page.navigate', { url: `http://localhost:4173/#${p.hash}` });
    await sleep(200);
    await cdp.send('Page.reload');
    await sleep(1500);
    await takeScreenshot(`${p.name}_desktop.png`);
  }

  // Capture Responsive Views (Tablet 768x1024 and Mobile 375x812)
  console.log('Capturing Tablet & Mobile responsive views...');
  await setViewport(768, 1024);
  await cdp.send('Page.navigate', { url: 'http://localhost:4173/#overview' });
  await sleep(200);
  await cdp.send('Page.reload');
  await sleep(1500);
  await takeScreenshot('02_overview_tablet.png');

  await cdp.send('Page.navigate', { url: 'http://localhost:4173/#operators' });
  await sleep(200);
  await cdp.send('Page.reload');
  await sleep(1500);
  await takeScreenshot('03_operators_tablet.png');

  await setViewport(375, 812, true);
  await cdp.send('Page.navigate', { url: 'http://localhost:4173/#overview' });
  await sleep(200);
  await cdp.send('Page.reload');
  await sleep(1500);
  await takeScreenshot('02_overview_mobile.png');

  await cdp.send('Page.navigate', { url: 'http://localhost:4173/#operators' });
  await sleep(200);
  await cdp.send('Page.reload');
  await sleep(1500);
  await takeScreenshot('03_operators_mobile.png');

  await cdp.send('Page.navigate', { url: 'http://localhost:4173/#devices' });
  await sleep(200);
  await cdp.send('Page.reload');
  await sleep(1500);
  await takeScreenshot('04_devices_mobile.png');

  console.log('All visual review screenshots captured successfully!');
  cdp.close();
  chromeProcess.kill();
  process.exit(0);
}

main().catch((err) => {
  console.error('Fatal error in capture script:', err);
  process.exit(1);
});
