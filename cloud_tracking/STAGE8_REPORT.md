# Stage 8 deployment report — 2 November 2026

Dashboard deployed. Owner login and TOTP/AAL2 verified. Physical pilot preparation
is available; monitoring activation and company-wide rollout remain unauthorized.

## Deployment

- Production: https://efl-nexus-admin.netlify.app
- Netlify project: `efl-nexus-admin`, team `akash-mithun` (CSS).
- Site ID: `7d9dac86-9cf2-486c-be72-0997a5ab780b`.
- Final deploy: `6ae8c178eb72cf93f470cde6`, production, **ready**.
- Published: **2 November 2026, 22:29:40 Asia/Colombo**.
- Netlify upload/deploy processing: 3 seconds; no server-side build was run.
- The connected team initially had no sites. The existing React dashboard source
  was deployed into this new hosting site; the Supabase backend was preserved.
- Netlify MCP performed project creation, production environment configuration,
  and deployment verification. Its available tools did not expose a deploy/upload
  operation, so the verified local build was uploaded with Netlify Drop through
  the authenticated browser.
- The site retains Netlify's default private/team-login access protection.
  An unauthenticated HTTP request returned 401; the team-authorized browser opened
  the dashboard successfully. No visibility protection was removed.
- Git continuous deployment is not linked. Root `netlify.toml` retains base
  `cloud_tracking/dashboard`, command `npm run build`, publish `dist`. This manual
  deploy uploaded that directory's built assets; it did not push the dirty checkout.

## Build and audit results

The branch remains `Nexus-Grabber`. Existing tracked modifications and untracked
monitoring/dashboard work were preserved. No commit or push was performed.

Executed in Stage 8:

| Check | Result |
| --- | --- |
| Clean dependency install | `npm ci --ignore-scripts` passed |
| npm audit during clean install | 0 vulnerabilities |
| Frontend regression suite | 44 passed across 6 files |
| Production build | `tsc && vite build` passed; final Vite build 902 ms |
| Published entry script | `/assets/index-_f4DlRcw.js`, confirmed in live DOM |
| Final artifact scan | 13 files; no matched service-role JWT, Supabase secret-key, or private-key patterns |
| Direct SPA path | `/stage8-routing-check` loaded the dashboard login |
| Netlify routing/header processing | 1 redirect rule and 1 header rule processed without errors |

The initial sandboxed build/test attempts failed on process/native-module access;
the same commands passed with normal process permissions. The package manifest
and old lockfile disagreed about Vite, Vitest and TypeScript. The manifest now
uses the installed tool versions (Vite 8.3.5, Vitest 5.0.5, TypeScript 7.0.2), and
a regenerated lockfile passed clean installation. No application framework was replaced.

Narrow frontend corrections made during the audit:

- Subscribe to the existing private `nexus:monitoring` broadcast channel.
- Defer SDK refresh calls out of the auth-event callback.
- Preserve the backend's terminal `offline` snapshot status.
- Count only active/idle sessions in Module Activity.
- Read the daily session count with a separate RLS-protected count query, because
  the snapshot includes open/latest device sessions rather than all history.
- Replace unsupported ten-minute AAL2 expiry and automatic recovery promises with
  accurate guidance. Correct the documented publish path relative to the base.
- Include `_redirects` and `_headers` in Vite's public assets so manual deployment
  preserves SPA behavior and security headers. CSP includes the existing Supabase
  HTTPS/WSS endpoint and denies objects and framing.

Netlify confirmed header-rule processing. A separate authenticated HTTP response
header capture was not collected behind the private-site gate; the unauthenticated
gate response included HSTS. Do not interpret source inspection as such a capture.

Stage 7 Python correction: **328 passed, 5 skipped, 333 discovered**. These are
owner-supplied prior results, not a Stage 8 Python rerun. See
[the correction addendum](STAGE7_CORRECTION.md). No original Stage 7 report file
was present locally to edit in place.

## Environment and Supabase

| Location | Setting | Verified value/status |
| --- | --- | --- |
| Netlify, production context | `VITE_SUPABASE_URL` | `https://wykmgymitdxkqbpywpzh.supabase.co` |
| Netlify, production context | `VITE_SUPABASE_ANON_KEY` | Existing enabled **publishable** key, verified through Supabase MCP |
| Netlify, production context | `NODE_VERSION` | `24` |
| Supabase Edge environment | `NEXUS_ADMIN_ORIGINS` | `https://efl-nexus-admin.netlify.app` |
| Supabase Auth | Site URL | `https://efl-nexus-admin.netlify.app` |
| Supabase Auth | Redirect allowlist | Exactly `https://efl-nexus-admin.netlify.app/` |
| Supabase Auth | TOTP enrollment/verification | Enabled and persisted after reload |

The Netlify plan rejected granular Builds-only scope; the three non-secret values
use all scopes in the production context. No service-role key, secret API key,
database password, connection string, owner password or TOTP material was copied
to Netlify or the deployment package.

The existing project `wykmgymitdxkqbpywpzh` was ACTIVE_HEALTHY. The deployed origin
parser was inspected before configuration: it splits commas, trims whitespace,
and requires an exact match. No wildcard, path or trailing slash was added to CORS.

Live checks:

| Request | Observed result |
| --- | --- |
| `admin-control` preflight, production origin | 204; exact allow-origin and required request headers |
| `admin-control` preflight, unapproved origin | 403 `origin_not_allowed`; no allow-origin |
| Browser-origin preflight to either desktop endpoint | 403 `desktop_only` |
| Snapshot without login | 401, database code `42501` |
| Device read without login | 401, database code `42501` |
| Administrator action without login | 401 `user_session_required` |
| Owner AAL2 administrator list | Successful in the deployed dashboard |

All three existing Edge Functions remain ACTIVE. RLS remains enabled on all six
public monitoring/admin tables checked. The private Realtime policy still requires
authenticated administrator AAL2. No schema, RLS policy or Edge Function code was
changed remotely, and no production records were deleted.

One existing security advisory remains: leaked-password protection is disabled.
Its setting was not changed as part of deployment. Official reference:
https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection

## Owner authentication and deployed dashboard verification

The owner personally signed in and completed authenticator enrollment. Supabase
initially rejected enrollment because TOTP was not enabled. Enabling the project
TOTP capability resolved that error. The owner then retried and completed enrollment.

Confirmed independently:

- Owner account active and email-confirmed.
- One verified TOTP factor in `auth.mfa_factors` (only the count was selected).
- Latest owner `auth.sessions.aal` is `aal2`.
- Deployed UI displays **AAL2 Verified** and one registered, verified factor.
- Owner AAL2 survives a normal dashboard reload.
- Snapshot, Live Operators, Devices, Session History and the protected administrator
  list load existing production-schema integration records.
- Four device records exist, including one previously revoked device. All four
  session-history records load. The corrected daily count is four.
- No current active sessions were observed. Existing snapshot statuses include
  offline, revoked and disconnected; they are not proof of physical pilot activity.
- Private Realtime refresh was tested with polling temporarily set to 60 seconds.
  Sending the existing refresh-only private broadcast changed the UI's Updated
  timestamp from 22:26:40 to 22:27:00, before the next poll. Default 15-second polling
  was restored. This sent no desktop telemetry and activated no monitoring.

No password, QR image, TOTP seed or verification code was requested, inspected or
logged by the agent. Screenshots show completed status, not enrollment secrets.

## Pilot readiness and remaining work

[Read-only workstation inventory](pilot_preflight.py) and the
[pilot runbook](stage8/PILOT_RUNBOOK.md) are prepared. The
[runtime-hook template](stage8/pilot_runtime_hook.py) is dormant, has no designated
installation UUIDs, and has `OWNER_AUTHORIZED = False`. It is not included in the
ordinary desktop spec. Its disabled path was executed and left the default gate False.
No pilot binary has been built or distributed.

Required before physical pilot acceptance:

1. Identify the two actual designated computers and installation UUIDs.
2. Validate identity, machine credential decryption, ACLs and server enrollment on
   each workstation, under the designated Windows accounts. Validate KPI identity,
   device fallback and each account's SQLite queue with the real config paths.
3. Obtain separate owner authorization before preparing an enabled two-UUID pilot
   build and activating it only after successful provisioning.
4. Verify physical background heartbeats, lifecycle, offline/restart recovery,
   synchronization and approved device revocation. These destructive/mutating
   acceptance actions were not repeated on existing production devices.

`READY_FOR_DEVICE_PILOT` remains **False**. No global monitoring, ordinary installer,
updater manifest or company-wide rollout was changed.

## Evidence

- [Machine-readable deployment evidence](stage8/deployment-evidence.json)
- [Build file SHA-256 manifest](stage8/build-sha256.json)
- ZIP SHA-256: `D62FE8C17275D23481541D3C49B95CE14AE92F97CE4111A85742E4E5516EC55E`
- [Netlify published state](stage8/04-netlify-published.jpg)
- [Production overview](stage8/07-production-overview.jpg)
- [Live operator status](stage8/08-production-operators.jpg)
- [Device inventory](stage8/09-production-devices.jpg)
- [Session history](stage8/10-production-sessions.jpg)
- [Completed owner MFA/AAL2](stage8/11-production-aal2.jpg)
- [Production Auth URLs](stage8/02-auth-urls.jpg)
- [TOTP capability enabled](stage8/06-totp-enabled.jpg)
