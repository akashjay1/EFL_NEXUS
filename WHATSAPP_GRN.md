# WhatsApp photo → reviewed GRN form

Open **WhatsApp → GRN Inbox** in NEXUS. Incoming photos in the existing selected
group are saved locally, read by Tesseract, and checked against the linear
barcode beneath the printed GATE PASS header when it can be decoded. GDN text
capture remains active in the same group.

## Use

1. Select the WhatsApp group using the existing Browser setup. Choose a
   **Default GRN warehouse** and click **Save GRN Warehouse**. The choice belongs
   to this group; it is not inferred from the photograph.
   If a restart shows **Group selection required**, open the saved group in the
   Browser tab. The adapter restores the exact saved name through validated pointer interactions
   and verifies the selected group before capture. If restoration is unavailable
   or ambiguous, capture resumes after you open the saved group manually.
2. Only incoming GRN photos received **within the last hour** are eligible for
   new scans and automatic photo capture. The cutoff uses the WhatsApp received
   timestamp, never the time the app first noticed the photo. Older photos,
   future timestamps and missing/unsupported received times are skipped; the
   scan status reports skipped counts. The verified adapter's day/month/year
   display format is interpreted in the PC/browser's local time zone. The window
   also applies to queued capture retries. Existing captured review records stay
   available, and work already started can finish.
   New eligible incoming photos appear in **GRN Inbox**. Existing visible history is
   skipped on first setup/upgrade. For an earlier message within the last hour, pause, scroll to it,
   then choose **Scan GRN**. The scan captures currently loaded incoming photos
   and runs OCR without resuming paused monitoring or scrolling through history.
   Resume monitoring afterward when ready.
3. Select a document. Compare its original photo, header crop, gate pass, and
   warehouse. Correct the fields and tick **I checked the number and warehouse**.
4. Choose **WhatsApp Lane 1** or **WhatsApp Lane 2**, then **Run Gatepass** to fill the lane and
   immediately start its existing **Create GRN** browser automation. The review
   confirmation checkbox is still required. To prepare the fields first, use
   **Fill GRN Form**, then open that WhatsApp lane tab and click **Create GRN** when
   ready. Filling alone does not start the browser flow or a queue.

Save edits before selecting another photo. OCR retries preserve saved review
corrections. **Run Gatepass** can run a previously filled or completed photo again
after its current run stops. The **State** column shows **New**, **Running**, or
**Completed**, independently of OCR and form-transfer status. Completed is set
only when the GRN flow finishes successfully, including its report/print steps.
Failed/stopped runs return to New; restart also releases an interrupted run
without claiming success. Each attempt is saved, and completion can be persisted
even if its inbox view closes. Matching active runs and waiting/running queue
items still block overlapping jobs. **Fill GRN Form** retains its duplicate
transfer guard; use **Run Gatepass** for an intentional repeat. Cleared, DONE,
and replaced photos cannot be rerun from stale selections.
The next attempt closes its lane's previous browser before opening a fresh one
with that lane's profile.

The **Received** column uses the original WhatsApp message time when available;
fallback timestamps are explicitly marked **Captured**. **Clear List** hides
this tab's current documents and pending photos while keeping their history,
images, corrections, and duplicate protection. It does not clear the GDN tab or
remove lane jobs. Late downloads/OCR results and rescans cannot restore cleared
rows. **Retry Extraction** remains available for an active selected photo.

An exact quoted **DONE** reply, including one sent by you, hides the original
photo and any byte-identical copies already deduplicated into its review record.
The rule also applies to GDN text requests. Only loaded replies can be newly
observed; decisions persist after restart. `NOT DONE`, `DONE ✅`, and unquoted
DONE messages do not qualify. Unverified reply links leave items visible with
a diagnostic; see [WHATSAPP_GDN.md](WHATSAPP_GDN.md) for linkage details.

Matching warehouse/gate-pass photos are flagged. A matching request already
transferred or present in either lane's GRN queue blocks another transfer.
Identical photo bytes share one review record even when resent in a different
message. Recompressed photos can have different hashes; reviewed gate-pass
checks provide the additional duplicate guard.

## Capture and recognition limits

The experimental adapter polls the selected group every 0.5 seconds from Python.
As soon as a photo is detected, its durable source record appears in the GRN
Inbox, before download or OCR finishes. The list checks for updates every 250 ms
and updates rows in place, preserving the selection and unsaved edits. These are
polling intervals, not a guarantee about WhatsApp/network delivery time.

Captionless photos can use the rendered author marker when copyable-text metadata
is absent. Photos whose sender is still uncertain appear as **Sender verification
required**; they are not silently dropped or assumed incoming. Known outgoing
messages and quoted images are excluded. Group binding retains the exact-name
limitation described in [WHATSAPP_GDN.md](WHATSAPP_GDN.md).

The adapter opens the specific message's WhatsApp photo viewer, reads its loaded
`media-image` blob, and closes the viewer it opened. It excludes CSS-blurred,
hidden, incomplete, and nonlocal images. It never saves the chat thumbnail as an
original. An already open viewer or user interaction pauses automatic retrieval
until the viewer is closed. The Browser tab can briefly show this loading process.
If WhatsApp itself cannot load an original, the entry remains visible as waiting
or retrying; open/download that photo manually in WhatsApp if necessary. The app
cannot restore detail that is absent from the sender's original image.

One queued capture owns WhatsApp's single photo viewer until that capture finishes
or yields an actionable error. Message discovery continues independently, with a
MutationObserver retaining photo detections between the periodic scans. Captionless
photos and each rendered image in an album keep their own source records. An
observation-buffer overflow is reported for manual comparison with the group.
One slow photo does not hide other detected
entries or block text monitoring. Failed retrievals retry after 1, 2, 5, 15, then
30 seconds. Waiting for the viewer does not increase the failure backoff. Pending
photos outside rendered history stay listed; reopen their message to finish
capture. Complete offline history recovery is not provided.

For a previously captured blurred image, select its unreviewed inbox record and
choose **Retry Capture** with its message loaded. This replaces the image and
reruns OCR. Saved reviews and transferred records are protected. **View Full
Photo** offers Fit, 100%, and 200% views with scrollbars. Capture is limited to
20 MB and 30 megapixels per photo. The source is linked to a document only after
validated image bytes are written and the database transaction succeeds.

Local OCR has a ten-second document budget, searches four orientations, corrects
modest skew, and locates the header on a preview. It reads the number from the
original-resolution crop, with grayscale, contrast and adaptive-threshold variants
for difficult digits. Only the adjacent number/run qualifies; unrelated numbers
farther along the same text line are excluded. Only numbers adjacent
to a GATE PASS label in the upper half of the oriented photo qualify. Linear
barcodes must be spatially associated with that header. Other document numbers
and the body QR code are not substitutes. Identifiers remain strings; leading
zeroes are preserved and no six-digit length is assumed.

Independent OCR readings or a barcode disagreement leave the proposed gate pass
empty with the candidate values displayed. A single reading still needs visual
review. OCR can misread characters; its confidence is not a correctness guarantee.
No unreadable value is invented or corrected by replacing letters with digits.

## Optional OCR.space fallback

Cloud OCR is **disabled by default**, including in a fresh packaged installation.
Open **GRN Inbox ? OCR Settings**, enter your **OCR.space API key** and a positive
daily upload limit, and enable **Automatically upload difficult photos to OCR.space**.
The default API endpoint is `https://api.ocr.space/parse/image`; the website homepage
is not an API endpoint, and a website login is not an API key. PRO users may enter
their OCR.space `/parse/image` endpoint from their service email. Keys are kept in
Windows Credential Manager, never in the inbox database or release bundle.

Local failures, conflicting readings and recognition warnings can queue a separate
single cloud worker. It sends the detected header crop, or the oriented/full photo
when a trustworthy header crop is unavailable. Engine 2 is requested with word
position overlays. Automatic server rotation and scaling are disabled to keep those
coordinates tied to the uploaded pixels; the parser checks orthogonal coordinate
frames itself. Only digits spatially associated with GATE PASS qualify. Plain text
without word positions is insufficient. OCR.space does not provide word confidence
scores, so none are invented or displayed as a probability.

Uploads use HTTPS multipart POST with the API key in a header, and no generated
searchable PDF. JPEG compression preserves pixel dimensions; the app uses a
conservative 1,000,000-byte upload limit for free-plan compatibility. If the image
cannot fit without reducing resolution, it is left for manual review. The documented
service limits and account quotas still apply. No service key or subscription is
provided by NEXUS.

OCR.space returns its result synchronously. Uploads have a 60-second connect/read
budget and are never automatically resubmitted after a lost response or an uncertain
submission. Unlike Azure, OCR.space provides no accepted-operation handle to resume.
**Retry Cloud** explicitly permits another upload and quota usage. Interrupted
submissions remain uncertain after restart. Completed results are cached by image
hash, provider/recognition version and endpoint, avoiding repeated successful uploads.
The daily reservation limit follows the PC's local date and conservatively includes
failed or uncertain upload attempts.

Cloud-pending documents cannot be transferred to a lane. Saved corrections,
recaptures, cleared/DONE records and document revisions are checked before applying
late results. Distinct local, barcode or OCR.space candidates leave the proposed
number empty. Photo/warehouse confirmation remains required before GRN creation.

Existing Azure review history and cached results are retained. Earlier automatic
Azure settings are not reused for OCR.space and require reconfiguration in OCR
Settings; Azure credentials are never sent to OCR.space. Compatibility code can
retain explicitly configured legacy Azure jobs, with separate credentials and caches.

See the official [OCR.space API documentation](https://ocr.space/ocrapi) for API-key
registration, overlay fields and service limits. Before enabling automatic fallback,
check representative photos with independently verified gate-pass numbers. Local and
HTTP-double tests do not establish live OCR.space accuracy.

## Local files and Windows builds

Additive `grn_documents` and `grn_sources` tables live in the existing SQLite inbox
at `%LOCALAPPDATA%/EFL_NEXUS/whatsapp_gdn/inbox.sqlite3`. Original photos and derived
crops are under `grn_images` beside that database. Existing GDN rows are unchanged.
Photos and extracted text are not included in Git. OCR remains entirely local
unless the OCR.space fallback is explicitly configured and enabled as described above.

The browser helper owns separate local and cloud OCR worker threads, each with its own SQLite connection.
Capture callbacks, extraction, and Tk UI updates use separate execution paths,
so slow OCR does not block the monitoring heartbeat. Interrupted extraction is
retried after helper restart. **Retry Extraction** also restarts a stopped worker.

For a reproducible local comparison, prepare a private JSON manifest containing
`image`, independently verified digit-string `expected`, and optional `difficult`
for each sample. Then run `python tests/benchmark_grn_ocr.py MANIFEST OUTPUT_DIRECTORY`
with the OCR dependencies installed. An optional `--baseline PATH_TO_SAVED_GRN_OCR_PY`
compares against preserved source using the same runtime. Reports include correct,
incorrect and unresolved readings plus timings; this runner makes no cloud requests.
Keep actual photos distinct from transformed variants and do not interpret a small
sample comparison as a population accuracy estimate.

Install 64-bit Python 3.12 for NEXUS and the Python version embedded in AuditShip
(currently 3.14). From the repository directory, run either:

```powershell
.\build_standalone.bat
# Or, for a differential update (prompts for the next build number):
.\create_patch.bat
```

Both scripts call `prepare_build.bat`, create/reuse an isolated Python 3.12
environment under `build/nexus-build-python312`, install the runtime/build
requirements, and prepare OCR before compiling the maintained `EFL_NEXUS.spec`.
The patch path uses that same spec, so it includes OCR.space, recent-photo
filtering, ZXing, OpenCV and the portable Tesseract assets. Generated updater and
installer specs stay under `build/generated-specs` instead of replacing tracked
spec files. `NEXUS_BUILD_PYTHON` may point to an existing 64-bit Python 3.12
environment. `AUDITSHIP_PYTHON` may identify its separate matching interpreter
when automatic discovery through the Windows launcher is unavailable.

`build_release.py` inspects AuditShip's embedded Python version before running its
credential patch in a separate matching environment. It also verifies the frozen
GRN modules, OCR native extensions and runtime checksums before packaging. Both
release types exclude inbox state, GRN images, browser profiles, local settings
and environment files. Patch generation retains SHA-256 differential selection
and embeds the selected build number; completed review history is not shipped.
The standalone script additionally builds the installer and full release ZIP.
The preparer verifies the upstream Tesseract 5.5.3 Windows installer, the build
extraction tool, and the pinned English model against SHA-256 checksums. It
extracts rather than installs them, follows native PE dependencies, and retains
license files and provenance. Runtime assets are generated under
`assets/grn_ocr` and excluded from Git. The packaged app includes those assets,
ZXing-C++, OpenCV, and NumPy; target PCs need no separate OCR installation.

Evidence sources: [Tesseract release](https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3),
[image preprocessing guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html),
[ZXing Python bindings](https://github.com/zxing-cpp/zxing-cpp/tree/master/wrappers/python),
and [pywebview asynchronous evaluation](https://pywebview.flowrl.com/api/).

## Reproduce validation

```powershell
python -m unittest discover -s tests -p 'test_whatsapp*.py' -v
python -m unittest discover -s tests -p 'test_grn_ocr.py' -v
python tests/validate_grn_photo.py PATH_TO_SAMPLE_PHOTO build/grn-validation/recheck
```

Set `NEXUS_GRN_SAMPLE` to the supplied photo's path to enable its ground-truth
unit check (`734355`). Storage snapshots, generated documents, and lane doubles
in tests are explicitly labelled. They do not prove live WhatsApp compatibility.
The photo validation script reports the original plus clearly marked transformed
copies; these are not independent documents or a production accuracy estimate.

### Observed validation, 2026-10-20

- 52 WhatsApp storage, monitoring, review, and real-form checks passed, together
  with five real OCR checks, six main-app bridge checks, and ten Pending Jobs
  gate-pass checks. The real-form check filled the GRN tab with leading zeroes
  while its browser driver remained unset.
- The supplied photo read `734355` from both printed text and the header barcode.
  Another incoming group photo was captured automatically and read `734734`,
  matching its visible header. A pixelated third photo was retained with a blank
  gate pass for review. No GRN creation flow was run during validation.
- The original and eight transformed copies produced eight correct proposals
  and one blank proposal for conflicting readings on a tilted copy. No incorrect
  nonempty proposal remained in that run. This is a small robustness check, not
  an accuracy estimate. Local evidence is under `build/grn-validation` (ignored
  by Git), including `verified-variants/results.json`.
- A 65-second minimized source observation recorded 33 healthy Monitoring
  samples, one helper run, and maximum heartbeat age 2.02 seconds. It does not
  establish new-message arrival latency. Restart preserved login, EGDC default,
  and captured images; the saved group needed manual reopening as noted above.
- The final packaged executable started with the saved inbox and EGDC default.
  Its bundled OCR worker reprocessed the supplied photo as `734355` from both
  text and barcode. Inspection of its embedded code confirmed the recapture
  implementation was included. Local evidence: `frozen-final-check.json`.
- The Windows installer and update ZIP were built. Their application, Tesseract,
  and model payloads matched the tested directory build by SHA-256; captured
  photos, inbox databases, and WebView profiles were absent. Evidence:
  `installer-payload-check.json` and `zip-check.json` under the validation folder.

### Photo/list refresh correction, 2026-10-20

The source now polls at 0.5 seconds and lists durable detections before retrieval
or OCR. Storage/UI tests cover visible pending rows, uncertain senders, selective
retry scheduling, and preserving an edited selection. Seven JavaScript state
checks use an explicitly labelled DOM/media double to cover full-viewer capture,
blurred/incomplete/missing full images, an existing user viewer, wrong groups,
and fetch failure. These doubles do not establish WhatsApp markup compatibility.

A real linked WebView2 session verified opening the selected incoming photo,
retrieving a clear 1200 ? 1600 full-viewer image (248,758 bytes), and closing the
owned viewer in 1.22 seconds. This was an already rendered photo, not an incoming
arrival-latency test. Evidence: `build/grn-validation/full-viewer-verification.json`
and `full-viewer-verified.image`, excluded from Git. New message arrival latency,
large bursts and unavailable-original recovery still require live observation.

The final check ran 66 WhatsApp tests and 16 existing main-app/Pending Jobs
regressions successfully. The real photo above read `734744` from both printed
text and its header barcode, with no OCR warnings. The directory build completed
successfully, and its real frozen helper embedded and exited cleanly (code 0)
using a separate temporary, logged-out profile. Evidence: `photo-fix-tests.log`,
`photo-fix-ocr-check.json`, `photo-fix-build.log`, and
`photo-fix-frozen-smoke.json` under `build/grn-validation`. The running application
was subsequently observed Monitoring the saved group with a fresh heartbeat and
no gap flag. The installer/update ZIP from the earlier build was not regenerated
for this correction; use the refreshed directory build or the current source.
