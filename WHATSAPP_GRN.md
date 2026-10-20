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
   Browser tab. The observed WhatsApp version did not reliably reopen that chat
   through the existing automatic restoration adapter, although login and inbox
   records persisted. Capture resumes after the saved group is open.
2. New incoming photos appear in **GRN Inbox**. Existing visible history is
   skipped on first setup/upgrade. For an older message, pause, scroll to it,
   then choose **Import Visible Photos**. Resume monitoring afterward.
3. Select a document. Compare its original photo, header crop, gate pass, and
   warehouse. Correct the fields and tick **I checked the number and warehouse**.
4. Choose **Lane A** or **Lane B**, then **Fill GRN Form**. Open Korber Automation
   and click the existing **Create GRN** button when ready. Filling never starts
   a browser flow, creates a GRN, or starts a queue automatically.

Save edits before selecting another photo. OCR retries preserve saved review
corrections. A previously transferred photo cannot be transferred again from
the inbox; check the target lane if transfer was interrupted. This status records
form transfer, not successful GRN creation in the portal.

Matching warehouse/gate-pass photos are flagged. A matching request already
transferred or present in either lane's GRN queue blocks another transfer.
Identical photo bytes share one review record even when resent in a different
message. Recompressed photos can have different hashes; reviewed gate-pass
checks provide the additional duplicate guard.

## Capture and recognition limits

The experimental adapter reads verified incoming message rows from the rendered
WhatsApp page. A photo is one `image-thumb` container, which can hold both a
thumbnail and a full image. Capture chooses its largest loaded image and reads
only local `blob:https://web.whatsapp.com/` media. Quoted reply images, avatars,
stickers, document attachments, PDFs, and unverified senders are not imported
as document photos. Group binding retains the existing exact-name limitation
described in [WHATSAPP_GDN.md](WHATSAPP_GDN.md).

Retrieval failures remain visible and retry every 30 seconds. If the full photo
is not loaded, open it in WhatsApp, close the viewer, and choose **Retry Capture**.
If WhatsApp shows a file-size download overlay, download that photo first. A
full-size blurred preview can have the same dimensions as the original. If the
inbox image is blurred, load the original in WhatsApp, select its unreviewed
inbox record, then choose **Retry Capture** to replace the local image and rerun
OCR. Saved reviews and transferred records cannot be replaced by recapture.
If the row has left the rendered history, load that message again. Unsupported
markup or unavailable media is not silently treated as a completed capture.
Capture is limited to 20 MB and 30 megapixels per photo. Media metadata is saved
first; the source is linked to a document only after validated image bytes are
written and the database transaction succeeds.

OCR tries four orientations, corrects modest skew, and uses adaptive thresholding
when camera borders or shadows prevent header detection. Only numbers adjacent
to a GATE PASS label in the upper half of the oriented photo qualify. Linear
barcodes must be spatially associated with that header. Other document numbers
and the body QR code are not substitutes. Identifiers remain strings; leading
zeroes are preserved and no six-digit length is assumed.

Independent OCR readings or a barcode disagreement leave the proposed gate pass
empty with the candidate values displayed. A single reading still needs visual
review. OCR can misread characters; its confidence is not a correctness guarantee.
No unreadable value is invented or corrected by replacing letters with digits.

## Local files and Windows builds

Additive `grn_documents` and `grn_sources` tables live in the existing SQLite inbox
at `%LOCALAPPDATA%/EFL_NEXUS/whatsapp_gdn/inbox.sqlite3`. Original photos and derived
crops are under `grn_images` beside that database. Existing GDN rows are unchanged.
Photos and extracted text are not uploaded to an OCR service or included in Git.

The browser helper owns an OCR worker thread with its own SQLite connection.
Capture callbacks, extraction, and Tk UI updates use separate execution paths,
so slow OCR does not block the monitoring heartbeat. Interrupted extraction is
retried after helper restart. **Retry Extraction** also restarts a stopped worker.

Prepare and build with Python 3.11 from the repository directory:

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
python prepare_grn_ocr.py
python -m PyInstaller EFL_NEXUS.spec --noconfirm
```

`build_standalone.bat` runs preparation and builds the existing installer too.
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
