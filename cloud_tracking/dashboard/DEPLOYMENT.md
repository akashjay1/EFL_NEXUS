# EFL NEXUS Administrator Dashboard – Production Deployment Guide

This guide provides step-by-step instructions for deploying the **EFL NEXUS Cloud Administrator Dashboard** to Netlify.

---

## 1. Architecture & Security Separation

### Frontend Environment Variables (Netlify Site Settings)
Configure these variables in **Netlify Site Configuration > Environment Variables**:

| Variable Name | Required | Example / Approved Value | Description |
| :--- | :---: | :--- | :--- |
| `VITE_SUPABASE_URL` | **Yes** | `https://wykmgymitdxkqbpywpzh.supabase.co` | Supabase EU-West-1 Project Endpoint |
| `VITE_SUPABASE_ANON_KEY` | **Yes** | `sb_publishable_4kmXj_vznXL8qyK5hFXeoQ_eSGi3xkR` | Public Anonymous Client Key |

> [!CAUTION]
> **NEVER** expose the Supabase `service_role` key or database connection string to Netlify or frontend code. The dashboard operates exclusively via authenticated user JWTs with Row-Level Security (RLS) and AAL2 TOTP authorization.

### Supabase Edge Function Secrets (Supabase CLI / Dashboard)
The `admin-control` Edge Function enforces strict CORS origin allowlisting via the `NEXUS_ADMIN_ORIGINS` secret.

Once the Netlify site is provisioned, add its production domain to the Supabase secret:

```bash
# Example using Supabase CLI
supabase secrets set NEXUS_ADMIN_ORIGINS="https://your-site-name.netlify.app,https://admin.eflnexus.internal"
```

---

## 2. Build & Routing Configuration

The repository contains `netlify.toml` at both the root and `cloud_tracking/dashboard/netlify.toml`:

```toml
[build]
  base = "cloud_tracking/dashboard"
  command = "npm run build"
  publish = "dist"

[build.environment]
  NODE_VERSION = "24"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200

[[headers]]
  for = "/*"
  [headers.values]
    X-Frame-Options = "DENY"
    X-Content-Type-Options = "nosniff"
    Referrer-Policy = "strict-origin-when-cross-origin"
    Permissions-Policy = "camera=(), microphone=(), geolocation=()"
    Content-Security-Policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://wykmgymitdxkqbpywpzh.supabase.co wss://wykmgymitdxkqbpywpzh.supabase.co; img-src 'self' data: blob:; font-src 'self' data:;"
```

---

## 3. Deployment Methods

### Option A: Netlify Git Continuous Deployment (Recommended)
1. Push branch to the remote repository.
2. Link the repository in Netlify Dashboard:
   - **Base directory**: `cloud_tracking/dashboard`
   - **Build command**: `npm run build`
   - **Publish directory**: `dist` (relative to the configured base directory)
3. Add environment variables:
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`
4. Trigger production deploy.

### Option B: Netlify CLI Single-Command Deploy
Run from `cloud_tracking/dashboard`:

```bash
# 1. Build production assets locally
npm run build

# 2. Deploy preview to test
npx netlify deploy --dir=dist

# 3. Deploy to production
npx netlify deploy --prod --dir=dist
```

---

## 4. Post-Deployment Verification Checklist

1. **SPA Routing**: Navigate directly to `https://<site>/#overview`, `/#operators`, `/#devices`. Ensure no 404s.
2. **Security Headers**: Inspect HTTP response headers using browser DevTools. Verify `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Content-Security-Policy`.
3. **Authentication**: Sign in with authorized administrator credentials.
4. **MFA Elevation**: Verify that accessing device provisioning prompts for the 6-digit TOTP code and achieves `AAL2 Verified`.
5. **Realtime Broadcast**: Confirm green `Supabase Connected` indicator lights up and receives private broadcasts on `nexus:monitoring`.
