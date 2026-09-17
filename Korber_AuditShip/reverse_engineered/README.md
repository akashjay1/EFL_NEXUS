# GatePassSummarySystem reverse-engineering report

## Result

`GatePassSummarySystem.exe` is an unsigned, 64-bit Windows GUI executable built with PyInstaller 6.22.2 and CPython 3.14. Its application entry point is an embedded Python module named `FINAL_CODE2_DEFAULT_KAWSHI.py`. The module contains roughly 4,100 original source lines, 183 code objects (including nested functions and lambdas), and 113 named top-level functions/classes.

The executable SHA-256 is:

```text
7440a102324802ba28086eb236a4ba2f338d8ced97d80db7f55708f305641661
```

The original Python formatting and comments cannot be reproduced exactly from bytecode. The generated `.pyc`, raw marshalled code object, complete CPython disassembly, and structural manifest preserve the executable logic that can be recovered exactly.

## Generated artifacts

- `FINAL_CODE2_DEFAULT_KAWSHI.pyc`: importable-style CPython 3.14 bytecode with a reconstructed header.
- `FINAL_CODE2_DEFAULT_KAWSHI.marshal`: the exact decompressed entry-module payload from the PyInstaller archive.
- `FINAL_CODE2_DEFAULT_KAWSHI.dis.txt`: full instruction-level disassembly of every application code object.
- `manifest.json`: archive layout plus function names, original line numbers, arguments, locals, referenced symbols, and constants.
- `../reverse_engineer.py`: reproducible extractor. It requires PyInstaller and the Python minor version used to build the target.

Running `reverse_engineer.py` without arguments extracts the artifacts and then opens the application GUI through the original PyInstaller executable. The bootloader is retained as the execution host because the extracted `.pyc` depends on modules and runtime initialization stored in PyInstaller's nonstandard `PYZ.pyz` archive. Use `python reverse_engineer.py --extract-only` when only the analysis artifacts are wanted. If the script is started with Python 3.12, it automatically finds and relaunches itself with Python 3.14 because disassembly must use the bytecode's matching minor version.

## Application purpose

The program is a CustomTkinter desktop tool called **Gate Pass Summary System** / **Korber Load Audit & Shipping BOT**. It combines an Excel viewer with Selenium automation for the Körber One Mobile web application.

The main state is held in module globals:

```text
df_global              uploaded three-column DataFrame
table_data             cleaned, sorted, deduplicated UI/export DataFrame
table_widget           paged Treeview wrapper
driver_global          Selenium Edge driver attached through remote debugging
door_location_global   door entered during upload and applied to every row
browser_thread         the one allowed browser/automation worker
stop_event             cooperative cancellation flag
```

The aligned table has six columns:

```text
Wh Id | Load Id | Gate Pass Id | Door Location | Load Audit Status | Shipping Status
```

## Execution flow

### Excel import

1. The user chooses an `.xls` or `.xlsx` file and enters one Door Location.
2. A daemon worker reads exactly `Wh Id`, `Load Id`, and `Gate Pass Id` with pandas.
3. The Door Location is copied to all rows and both status columns start empty.
4. Rows are deduplicated on the four data columns, stably sorted by warehouse/load/gate-pass, and shown in a paged `ttk.Treeview`.
5. Cell values can be copied. The aligned data can be exported to `.xlsx` or a landscape A4 PDF headed `3PL EFL`.

### Open Browser

1. The first aligned row determines the selected warehouse. Only `LPPL`, `ESKD`, `NUGE`, and `EGDC` are accepted.
2. Edge is started with a persistent profile at `~/Edge_LPAKASHM_Profile`, remote-debugging port `9222`, and the production Körber URL.
3. Selenium attaches to `127.0.0.1:9222` using the `eager` page-load strategy.
4. The program enters its embedded username/password, waits for Home Page, opens Körber One Mobile, handles the mobile Login and optional Fork Identifier screen, selects the warehouse, then opens `EFL > OUTBOUND`.
5. A recovery path repeatedly clicks RF Cancel/back, handles `Invalid Option`, and optionally clicks a final Submit before warehouse selection.

### Load Audit workflow

For every aligned row:

```text
LOAD ID       <- row Load Id
GATE PASS ID  <- row Gate Pass Id
LOCATION      <- the uploaded Door Location
Y OR N        <- N
ENTER:Confirm -> Submit
```

After each submit, the bot waits for either the expected next visible prompt or a visible Error dialog. Errors are uppercased, stored in `Load Audit Status`, acknowledged with OK, and the row is skipped. A special item-level quantity/loading screen is submitted once and stored as the misspelled status `Loding Issue`. A successful return to the Load ID screen stores `Done`.

### Shipping workflow

The user first supplies one Seal Number. For every aligned row:

```text
LOAD ID       <- row Load Id
GATE PASS ID  <- row Gate Pass Id
LOCATION      <- the uploaded Door Location
CARRIER NAME  <- DEFAULT
PRO NUMBER    <- row Load Id
SEAL NUMBER   <- the one user-entered seal
ENTER:Confirm -> Submit
```

Visible errors are acknowledged and copied into `Shipping Status`; successful rows are marked `Done`.

### Stop and close

`BOT STOP` sets the stop event, immediately calls `driver.quit()`, clears the global driver, and re-enables buttons. `Close Browser` first attempts to Cancel/back through RF screens and click the optional final Submit, then quits the browser even when that cleanup reports a warning.

Two globally detected Körber failures receive special treatment:

- “The Koerber One user has changed for this terminal”: dismiss, show a local warning, wait five minutes, then resume.
- “Advantage Workflow Engine is down”: dismiss, show a local warning, wait five minutes, then quit the browser.

## Browser interaction design

The automation uses several fallback layers: exact/contains XPath queries, JavaScript pointer/mouse events, normal element clicks, Selenium `ActionChains`, and finally Enter on the active element. It deliberately checks visible `innerText` instead of only `page_source`, because hidden Körber templates contain prompt words that otherwise produce false state transitions.

RF input fields are populated primarily by setting the native DOM `value` property and firing input/change events. If that fails, the code falls back to select-all/delete/send-keys. Stop checks are interleaved into short polling loops.

## Security and reliability findings

### High: plaintext credentials embedded in the executable

The production URL, login username, and login password are plain constants in the entry module. PyInstaller compression is packaging, not protection; the supplied extractor recovers them directly. Rotate the exposed credential, remove it from source/build artifacts, and obtain secrets at runtime from Windows Credential Manager or another approved secret store.

### High: local remote-debugging session can be taken over

Edge is deliberately launched with `--remote-debugging-port=9222` and a persistent authenticated profile. Any process running as the same machine user can probe that endpoint and potentially drive the logged-in browser. Use an ephemeral port/profile, tightly control the workstation, and close the debugging browser after each run. Do not treat the profile as a secret vault.

### Medium: `.xls` is advertised but its engine is absent

The file picker accepts legacy `.xls`, but the bundle includes `openpyxl` and does not include `xlrd`. `.xlsx` should work; `.xls` is expected to fail unless the build adds a compatible engine or the UI stops advertising it.

### Medium: automation and UI share mutable globals without locks

The GUI thread can call `driver.quit()` while a daemon worker is using the same driver. Most broad exception handlers turn this into a failure message, but state races are possible. Put browser ownership in one worker and send it stop commands rather than directly closing its driver from Tkinter callbacks.

### Medium: one warehouse and one seal are applied broadly

Browser selection uses only the first sorted row's warehouse, while the workflow then processes every row. There is no validation that all rows share that warehouse. Shipping applies one Seal Number to every row. Validate these invariants or group/confirm rows before submitting irreversible business operations.

### Low/medium: input validation is minimal

Door Location and Seal Number are checked only for non-empty strings. IDs are stringified; missing spreadsheet values can become values such as `nan`/`NAN`. Validate formats and reject missing values before opening the browser.

### Low: unsigned executable

The PE file has no Authenticode signature. This does not prove maliciousness, but users cannot verify publisher or detect replacement through Windows trust checks. Sign release builds and publish hashes through a trusted channel.

## Bundled runtime

Observed primary packages include Python 3.14, PyInstaller 6.22.2, CustomTkinter 5.2.2, Selenium 4.44.0, pandas 3.0.3, NumPy 2.4.4, openpyxl 3.1.5, Pillow 12.2.0, and ReportLab 4.5.1.

No evidence was found in the application module of persistence, privilege escalation, arbitrary command execution, data exfiltration, or communication with domains other than the configured Körber production site. The subprocess use is limited to starting Microsoft Edge with a fixed executable path and arguments. This is a static assessment; it does not prove the remote site or bundled native libraries are safe.
