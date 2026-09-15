# EFL NEXUS v1.0.7 — Release Notes

## Overview
**EFL NEXUS v1.0.7** introduces the fully integrated **User KPI** module (formerly EFL Data Entry) for comprehensive operator metric logging, live cloud synchronization, and automated queue integration, alongside a dedicated launcher, dynamic credential support, and Equipment Zone / Fork ID configuration for **Korber AuditShip**.

---

## What's New & Key Highlights

### 👥 User KPI Module — Core Features & Capabilities
- **Structured Task & Metric Logging**:
  - **Reconciliation & Load Plan**: Dedicated entry workflows for GDN Reconciliation, GRN Reconciliation, GDN Creation, GRN Creation, and Load Plan / ASN tasks with status toggles (`New` / `Revise`).
  - **Warehouse Operations**: Direct metric logging for Load Audit, Shipping, Load Transfer, and Allocation / Backorders, supporting job quantities and LP counts.
- **Live Google Sheets Cloud Synchronization**:
  - Secure service-account-backed live cloud syncing for real-time dispatch and metric recording.
  - Automatic background polling and sync health monitoring with a live `● Online` / `● Offline` status indicator.
  - Conflict avoidance, collision detection, and cross-operator assignment safeguards.
- **Automated Reconciliation Queue Integration**:
  - Automatically routes submitted GDN and GRN reconciliation entries directly into the persistent local reconciliation queue for immediate processing by the Load Reconciliation engine.
- **Operator Profile & Access Control**:
  - Individual operator identity management linked to registered `User ID` and `User Code`, ensuring accurate metric attribution.
- **Interactive Shift & Date Selector**:
  - Built-in calendar picker with quick "Today" navigation for logging and reviewing historical work shifts and daily logs.
- **One-Click Styled KPI Excel Export**:
  - Export formatted Excel KPI workbooks (`.xlsx`) complete with shift summaries, itemized operational counts, and user verification metadata.
- **Real-Time Task Rollback & Counter Badges**:
  - Delete and update recorded jobs on-the-fly with dynamic counter badges that reflect real-time submitted counts.

---

### 🚚 Korber AuditShip — Dynamic Credentials & Equipment Zone Support
- **Dedicated Launcher Screen**: Selecting *Korber AuditShip* presents a clean launcher interface with an **"Open AuditShip"** button, preventing unwanted background process execution until requested.
- **Dynamic Username & Password Support**: AuditShip now dynamically authenticates using operator credentials saved in EFL NEXUS Settings, replacing hardcoded login parameters.
- **Equipment Zone & Fork ID Support**: Full support for custom **Fork ID / Equipment Zone** identifiers. Operators are no longer constrained to hardcoded zone identifiers (`LPAKASHM`).
- **Password Visibility Toggle**: Added an **👁 Show / 🔒 Hide** toggle button for secure and accurate credential entry.
- **Action Required for First-Time Setup**:
  > **Important**: Before launching AuditShip for the first time, go to **Settings & System Status ➔ KORBER AUDITSHIP CREDENTIALS** and enter your **User Name**, **Password**, and **Fork ID / Equipment Zone**, then click **💾 Save Credentials**.

---

### ⚙️ Settings & System Diagnostics
- **Korber AuditShip Credentials Card**: Manage AuditShip **User Name**, **Password**, and **Fork ID** with live configuration validation pills (`● Configured` / `● Needs Setup`).
- **System Diagnostics Telemetry**: Added an `AuditShip Account:` diagnostic row showing active account and Fork ID status.

---

## Fixes & Improvements

- **Fixed Settings Save Failure**: Resolved an issue in `ConfigStore.save()` where implicit `None` return values triggered false *"Save Failed"* popups on valid credential updates.
- **Packaging & Differential Patch Optimization**:
  - `create_patch.py` now excludes user configuration (`config.json`), local task cache (`.efl_records_cache.json`), and temporary build files from patch archives.
  - `create_patch.bat` and `build_standalone.bat` now automatically synchronize `Korber_AuditShip` directory and include `kpi_profile` and `patch_auditship_credentials` in PyInstaller hidden imports.

---

## Version Metadata
- **Version**: `1.0.7` ([`version.txt`](file:///d:/EFL_NEXUS/version.txt))
- **Build**: `0` ([`build.txt`](file:///d:/EFL_NEXUS/build.txt))
