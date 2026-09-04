import ctypes
import os
import sys
import threading
import queue
import time
import calendar
import json
import hashlib
from datetime import datetime
import customtkinter as ctk

# Make the app sharp and clear on high-DPI Windows monitors
try:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

# ==========================================
# GOOGLE SHEETS CONFIGURATION & IMPORTS
# ==========================================
import gspread
from oauth2client.service_account import ServiceAccountCredentials

SHEET_ID = "1FyX5TQgoVluPYfFol6L0M813Aqov8eoC6fRk4lp1hn0"
SHEET2_NAME = "Sheet2"
SHEET3_NAME = "Sheet3"  # Worksheet for securely storing login details (User ID & Password Hash)
AUTO_REFRESH_INTERVAL = 10000  # 10 seconds for count refresh

def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

APP_PATH = get_app_path()
try:
    os.chdir(APP_PATH)
except Exception:
    pass

# ==========================================
# USER MANAGEMENT & CRYPTOGRAPHIC AUTHENTICATION
# ==========================================
USERS_FILE = os.path.join(APP_PATH, "efl_users.json")

def hash_password(password: str) -> str:
    """Hash password with SHA-256 so raw passwords are never saved or visible in plaintext"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def is_sha256_hash(text: str) -> bool:
    """Check if a string is a 64-character hexadecimal SHA-256 hash"""
    return len(text) == 64 and all(c in '0123456789abcdefABCDEF' for c in text)

def load_user_db():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "users" in data:
                    return data
        except Exception as e:
            print(f"Error loading user db: {e}")
    # Empty default database
    default_db = {
        "remembered_user": None,
        "users": {}
    }
    save_user_db(default_db)
    return default_db

def save_user_db(db):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)
    except Exception as e:
        print(f"Error saving user db: {e}")

def authenticate_user(username, password):
    username = username.strip()
    if not username:
        return False, "Please enter a User ID"
    db = load_user_db()
    users = db.get("users", {})
    
    # Case-insensitive lookup matching
    target_key = None
    for u in users:
        if u.lower() == username.lower():
            target_key = u
            break
            
    if not target_key:
        return False, "User ID not found. Please register first."
    
    user_data = users[target_key]
    if user_data.get("password_hash") == hash_password(password):
        return True, target_key
    return False, "Incorrect password"

def register_user(username, password, sync_remote=True):
    username = username.strip()
    if not username:
        return False, "User ID cannot be blank"
    if len(username) < 2:
        return False, "User ID must be at least 2 characters"
    if len(password) < 3:
        return False, "Password must be at least 3 characters"

    db = load_user_db()
    users = db.setdefault("users", {})
    for u in users:
        if u.lower() == username.lower():
            return False, "User ID already exists"

    pwd_hash = hash_password(password)
    users[username] = {
        "password_hash": pwd_hash,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_user_db(db)

    # Automatically save secure hash to Sheet3
    if sync_remote:
        threading.Thread(target=save_user_to_sheet3, args=(username, pwd_hash), daemon=True).start()

    return True, f"User '{username}' registered successfully"

def get_registered_users():
    db = load_user_db()
    return list(db.get("users", {}).keys())

def get_remembered_user():
    db = load_user_db()
    rem = db.get("remembered_user")
    if rem and rem in db.get("users", {}):
        return rem
    return None

def set_remembered_user(username, remember=True):
    db = load_user_db()
    db["remembered_user"] = username if remember else None
    save_user_db(db)


# ==========================================
# GOOGLE SHEETS DATA ACCESS
# ==========================================
# ==========================================
# CACHE AND PERSISTENCE
# ==========================================
_sheets_lock = threading.RLock()
_client_cache = None
_spreadsheet_cache = None
_sheet_cache = None
_records_cache = None
_sheet2_cache = None
_records2_cache = None
_sheet3_cache = None
_records3_cache = None
_cache_timestamps = {}
_connection_status = False

_count_cache = {}
_count_cache_timestamp = {}

CACHE_FILE = os.path.join(APP_PATH, ".efl_records_cache.json")

# ==========================================
# ACTIVITY & CONNECTION LOGGING SYSTEM
# ==========================================
_activity_logs = []
_activity_log_lock = threading.Lock()
_current_app_instance = None

def add_activity_log(category, message, level="INFO", details=""):
    """Thread-safe activity logger with timestamping and event dispatch."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {
        "timestamp": timestamp,
        "category": category, # "CONNECTION", "SYNC", "TASK", "CACHE", "AUTH", "SYSTEM"
        "level": level,       # "INFO", "SUCCESS", "WARN", "ERROR"
        "message": message,
        "details": details
    }
    with _activity_log_lock:
        _activity_logs.append(entry)
        if len(_activity_logs) > 300:
            _activity_logs.pop(0)

    if _current_app_instance and hasattr(_current_app_instance, '_on_activity_log_added'):
        try:
            _current_app_instance.root.after(0, lambda e=entry: _current_app_instance._on_activity_log_added(e))
        except Exception:
            pass

def test_connection_diagnostics():
    """Perform a deep connection and latency test against Google Sheets API."""
    results = {
        "connected": False,
        "latency_ms": 0,
        "sheets_found": [],
        "cache_records": (len(_records_cache or []) + len(_records2_cache or [])),
        "error": ""
    }
    t0 = time.time()
    try:
        sheet, msg = connect_to_sheets(force_refresh=True)
        t1 = time.time()
        results["latency_ms"] = max(1, int((t1 - t0) * 1000))
        if sheet:
            results["connected"] = True
            try:
                ss = sheet.spreadsheet
                results["sheets_found"] = [ws.title for ws in ss.worksheets()]
            except Exception:
                results["sheets_found"] = ["Sheet1", SHEET2_NAME, SHEET3_NAME]
            add_activity_log("CONNECTION", f"Connection verified in {results['latency_ms']}ms (Status: Online)", "SUCCESS", f"Worksheets: {', '.join(results['sheets_found'])}")
        else:
            results["error"] = msg
            add_activity_log("CONNECTION", f"Connection test failed: {msg}", "ERROR")
    except Exception as e:
        results["latency_ms"] = max(1, int((time.time() - t0) * 1000))
        results["error"] = str(e)
        add_activity_log("CONNECTION", f"Connection error: {e}", "ERROR")
    return results

def _save_local_disk_cache():
    """Save in-memory records to local disk cache for instant startup loading."""
    try:
        data = {
            "timestamp": datetime.now().timestamp(),
            "sheet1": _records_cache or [],
            "sheet2": _records2_cache or [],
            "sheet3": _records3_cache or []
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error saving local cache: {e}")

def _load_local_disk_cache():
    """Load records from local disk cache into memory in 0.001s."""
    global _records_cache, _records2_cache, _records3_cache, _cache_timestamps
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            ts = data.get("timestamp", datetime.now().timestamp())
            if _records_cache is None and "sheet1" in data:
                _records_cache = data.get("sheet1", [])
                _cache_timestamps["sheet1"] = ts
            if _records2_cache is None and "sheet2" in data:
                _records2_cache = data.get("sheet2", [])
                _cache_timestamps[SHEET2_NAME] = ts
            if _records3_cache is None and "sheet3" in data:
                _records3_cache = data.get("sheet3", [])
                _cache_timestamps[SHEET3_NAME] = ts
            tot = len(_records_cache or []) + len(_records2_cache or [])
            add_activity_log("CACHE", f"Loaded {tot:,} records from local disk cache", "INFO")
            return True
    except Exception as e:
        print(f"Error loading local cache: {e}")
    return False

# Attempt instant load of disk cache on module import
_load_local_disk_cache()

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
            target = os.path.join(base_path, relative_path)
            if os.path.exists(target):
                return target
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    target = os.path.join(base_path, relative_path)
    if os.path.exists(target):
        return target
    return os.path.join(APP_PATH, relative_path)

def get_credentials_path():
    return get_resource_path('credentials.json')

def connect_to_sheets(force_refresh=False, sheet_name=None):
    """Connect to Google Sheets with client and spreadsheet caching."""
    global _client_cache, _spreadsheet_cache, _sheet_cache, _sheet2_cache, _sheet3_cache, _connection_status
    with _sheets_lock:
        try:
            if not force_refresh:
                if sheet_name == SHEET3_NAME and _sheet3_cache:
                    _connection_status = True
                    return _sheet3_cache, "Success"
                elif sheet_name == SHEET2_NAME and _sheet2_cache:
                    _connection_status = True
                    return _sheet2_cache, "Success"
                elif (sheet_name is None or sheet_name == "Sheet1") and _sheet_cache:
                    _connection_status = True
                    return _sheet_cache, "Success"

            if not _spreadsheet_cache or force_refresh:
                creds_path = get_credentials_path()
                if not os.path.exists(creds_path):
                    _connection_status = False
                    return None, "credentials.json not found"

                scope = [
                    'https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive.file'
                ]
                creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
                _client_cache = gspread.authorize(creds)
                _spreadsheet_cache = _client_cache.open_by_key(SHEET_ID)

            spreadsheet = _spreadsheet_cache

            if sheet_name == SHEET3_NAME:
                try:
                    sheet = spreadsheet.worksheet(SHEET3_NAME)
                except Exception:
                    sheet = spreadsheet.add_worksheet(title=SHEET3_NAME, rows=100, cols=10)
                    sheet.append_row(['Timestamp', 'User ID', 'Password Hash'])
                _sheet3_cache = sheet
            elif sheet_name == SHEET2_NAME:
                sheet = spreadsheet.worksheet(SHEET2_NAME)
                _sheet2_cache = sheet
            else:
                sheet = spreadsheet.sheet1
                _sheet_cache = sheet

            _connection_status = True
            add_activity_log("CONNECTION", f"Connected to Google Sheets: '{spreadsheet.title}' ({sheet_name or 'Sheet1'})", "SUCCESS")
            return sheet, "Success"
        except Exception as e:
            _connection_status = False
            add_activity_log("CONNECTION", f"Connection error: {e}", "ERROR")
            return None, str(e)

def fetch_all_sheets_batch():
    """Fetch Sheet1, Sheet2, Sheet3 in a SINGLE batch API request (~0.7s)."""
    global _records_cache, _records2_cache, _records3_cache, _cache_timestamps, _connection_status
    with _sheets_lock:
        try:
            sheet, msg = connect_to_sheets()
            if not sheet:
                _connection_status = False
                add_activity_log("SYNC", f"Batch sync skipped (Offline): {msg}", "WARN")
                return False, msg

            spreadsheet = sheet.spreadsheet
            res = spreadsheet.values_batch_get(["Sheet1", SHEET2_NAME, SHEET3_NAME])
            value_ranges = res.get("valueRanges", [])

            def to_records(vr):
                vals = vr.get("values", [])
                if not vals or len(vals) < 2:
                    return []
                hdrs = [str(h).strip() for h in vals[0]]
                out = []
                for r in vals[1:]:
                    pad = list(r) + [""] * (len(hdrs) - len(r))
                    out.append({hdrs[i]: pad[i] for i in range(len(hdrs)) if hdrs[i]})
                return out

            now_ts = datetime.now().timestamp()
            if len(value_ranges) > 0:
                _records_cache = to_records(value_ranges[0])
                _cache_timestamps["sheet1"] = now_ts
            if len(value_ranges) > 1:
                _records2_cache = to_records(value_ranges[1])
                _cache_timestamps[SHEET2_NAME] = now_ts
            if len(value_ranges) > 2:
                _records3_cache = to_records(value_ranges[2])
                _cache_timestamps[SHEET3_NAME] = now_ts

            _connection_status = True
            _save_local_disk_cache()
            _count_cache.clear()

            # Sync user database in memory from Sheet3 records without extra requests
            sync_users_from_records(_records3_cache)

            tot = len(_records_cache or []) + len(_records2_cache or [])
            add_activity_log("SYNC", f"Synchronized {tot:,} records (Sheet1: {len(_records_cache or [])}, Sheet2: {len(_records2_cache or [])})", "SUCCESS")
            return True, "Success"
        except Exception as e:
            _connection_status = False
            add_activity_log("SYNC", f"Batch sync error: {e}", "ERROR")
            return False, str(e)

def preload_data():
    """Load local cache from disk and begin background batch sheet fetch."""
    _load_local_disk_cache()
    threading.Thread(target=fetch_all_sheets_batch, daemon=True).start()

def get_cached_records(force_refresh=False, sheet_name=None):
    global _records_cache, _records2_cache, _records3_cache, _cache_timestamps

    cache_key = sheet_name if sheet_name in (SHEET2_NAME, SHEET3_NAME) else "sheet1"
    current_time = datetime.now().timestamp()

    if not force_refresh:
        target_cache = _records3_cache if sheet_name == SHEET3_NAME else (_records2_cache if sheet_name == SHEET2_NAME else _records_cache)
        if target_cache is not None:
            # If cache is fresh, or if called on the main GUI thread, return immediately without blocking UI
            if (current_time - _cache_timestamps.get(cache_key, 0) < 60) or (threading.current_thread() is threading.main_thread()):
                if current_time - _cache_timestamps.get(cache_key, 0) >= 60:
                    threading.Thread(target=fetch_all_sheets_batch, daemon=True).start()
                return target_cache

    # If force_refresh or not in memory, use fast batch fetch
    success, _ = fetch_all_sheets_batch()
    if success:
        if sheet_name == SHEET3_NAME:
            return _records3_cache
        elif sheet_name == SHEET2_NAME:
            return _records2_cache
        else:
            return _records_cache

    # Fallback to single sheet fetch if batch fails
    sheet, msg = connect_to_sheets(force_refresh, sheet_name)
    if not sheet:
        return None

    try:
        records = sheet.get_all_records()
        _cache_timestamps[cache_key] = datetime.now().timestamp()
        if sheet_name == SHEET3_NAME:
            _records3_cache = records
        elif sheet_name == SHEET2_NAME:
            _records2_cache = records
        else:
            _records_cache = records
        _save_local_disk_cache()
        return records
    except Exception as e:
        print(f"Error fetching records ({sheet_name}): {e}")
        return None

def invalidate_cache(sheet_name=None):
    global _records_cache, _records2_cache, _records3_cache, _cache_timestamps, _count_cache, _count_cache_timestamp
    if sheet_name == SHEET3_NAME:
        _records3_cache = None
        _cache_timestamps.pop(SHEET3_NAME, None)
    elif sheet_name == SHEET2_NAME:
        _records2_cache = None
        _cache_timestamps.pop(SHEET2_NAME, None)
    elif sheet_name == "sheet1":
        _records_cache = None
        _cache_timestamps.pop("sheet1", None)
    else:
        _records_cache = None
        _records2_cache = None
        _records3_cache = None
        _cache_timestamps.clear()
    _count_cache.clear()
    _count_cache_timestamp.clear()

# ==========================================
# SHEET3 USER CREDENTIALS SECURE HASH PERSISTENCE & 2-WAY SYNC
# ==========================================
def save_user_to_sheet3(username, password_or_hash):
    """Save or update user login details in Sheet3 strictly as an unreadable cryptographic hash"""
    try:
        sheet, msg = connect_to_sheets(force_refresh=True, sheet_name=SHEET3_NAME)
        if not sheet:
            return False, msg

        # Ensure we always save a 64-char SHA-256 hash
        pwd_hash = password_or_hash.lower() if is_sha256_hash(password_or_hash) else hash_password(password_or_hash)
        records = get_cached_records(force_refresh=True, sheet_name=SHEET3_NAME)
        timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

        # If sheet has no records, ensure headers are present
        if not records:
            try:
                first_row = sheet.row_values(1)
                if not first_row:
                    sheet.append_row(['Timestamp', 'User ID', 'Password Hash'])
            except Exception:
                pass

        row_to_update = None
        if records:
            for i, record in enumerate(records, start=2):
                r_user = str(record.get('User ID', record.get('Username', record.get('User', '')))).strip()
                if r_user.lower() == username.strip().lower():
                    row_to_update = i
                    break

        if row_to_update:
            # Update password hash for existing User ID
            sheet.update(range_name=f"A{row_to_update}:C{row_to_update}", values=[[timestamp, username, pwd_hash]])
        else:
            # Append new user hash to Sheet3
            sheet.append_row([timestamp, username, pwd_hash])

        invalidate_cache(SHEET3_NAME)
        return True, "Saved user credentials hash to Sheet3 successfully"
    except Exception as e:
        print(f"Error saving user hash to Sheet3: {e}")
        return False, str(e)

def sync_users_from_records(records, sheet=None):
    """Sync user hashes between Sheet3 records and local database without extra network calls."""
    if records is None:
        return False, "No records provided"
    try:
        db = load_user_db()
        users = db.setdefault("users", {})
        changes = False

        sheet_valid_users = {}
        for i, record in enumerate(records, start=2):
            r_user = str(record.get('User ID', record.get('Username', record.get('User', '')))).strip()
            r_pass = str(record.get('Password Hash', record.get('Password', record.get('Pass', '')))).strip()
            r_time = str(record.get('Timestamp', '')).strip()

            if not r_user:
                continue

            if r_pass and is_sha256_hash(r_pass):
                pwd_hash = r_pass.lower()
            elif r_pass:
                pwd_hash = hash_password(r_pass)
                if sheet:
                    try:
                        sheet.update(range_name=f"C{i}", values=[[pwd_hash]])
                    except Exception:
                        pass
            else:
                continue

            sheet_valid_users[r_user.lower()] = (r_user, pwd_hash, r_time)

        # 1. Add / Update users that exist in Sheet3
        for r_user_lower, (orig_user, pwd_hash, r_time) in sheet_valid_users.items():
            target_key = None
            for u in users:
                if u.lower() == r_user_lower:
                    target_key = u
                    break

            key_to_use = target_key if target_key else orig_user
            if key_to_use not in users or users[key_to_use].get("password_hash") != pwd_hash:
                users[key_to_use] = {
                    "password_hash": pwd_hash,
                    "created_at": r_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                changes = True

        # 2. Purge / Delete users from local database who were removed from Sheet3
        users_to_remove = [u for u in list(users.keys()) if u.lower() not in sheet_valid_users]
        for u in users_to_remove:
            del users[u]
            changes = True

        # 3. Clear remembered user if deleted from Sheet3
        if db.get("remembered_user") and db.get("remembered_user").lower() not in sheet_valid_users:
            db["remembered_user"] = None
            changes = True

        if changes:
            save_user_db(db)

        return True, "Users synchronized"
    except Exception as e:
        print(f"Error syncing users from records: {e}")
        return False, str(e)

def sync_users_with_sheet3():
    """Sync user hashes between Sheet3 and local database."""
    try:
        sheet, msg = connect_to_sheets(force_refresh=False, sheet_name=SHEET3_NAME)
        if not sheet:
            return False, msg

        records = get_cached_records(force_refresh=False, sheet_name=SHEET3_NAME)
        if records is None:
            records = sheet.get_all_records()

        return sync_users_from_records(records, sheet)
    except Exception as e:
        print(f"Error syncing users with Sheet3: {e}")
        return False, str(e)

# ==========================================
# COUNT AND TASK OPERATIONS
# ==========================================
def calculate_all_task_counts(user_id, target_date=None):
    """Calculate all task counts for user_id on target_date in a single fast pass (<1ms)."""
    target_str = target_date.strftime("%d-%m-%Y") if target_date else datetime.now().strftime("%d-%m-%Y")
    norm_user = user_id.strip().lower()

    counts_map = {
        "GDN Reconciliation:": 0,
        "GRN Reconciliation:": 0,
        "GDN Creation:": 0,
        "GRN Creation:": 0,
        "Load Plan or Asn:": 0,
        "Load Transfer:": [0, 0],
        "Load Audit:": [0, 0],
        "Shipping:": [0, 0],
        "Allocation/Backorders:": [0, 0]
    }

    records1 = _records_cache or []
    for r in records1:
        u = str(r.get('User ID', '')).strip().lower()
        if u != norm_user:
            continue
        ts = str(r.get('Timestamp', ''))
        if target_str not in ts:
            continue
        t = str(r.get('Task', '')).strip()
        if t in counts_map and isinstance(counts_map[t], int):
            counts_map[t] += 1

    records2 = _records2_cache or []
    for r in records2:
        u = str(r.get('User ID', '')).strip().lower()
        if u != norm_user:
            continue
        ts = str(r.get('Timestamp', ''))
        if target_str not in ts:
            continue
        t = str(r.get('Task', '')).strip()
        if t in counts_map and isinstance(counts_map[t], list):
            load_str = str(r.get('Load ID', '')).strip()
            lp_str = str(r.get('LP Count', '')).strip()
            if load_str:
                try:
                    counts_map[t][0] += int(load_str)
                except ValueError:
                    pass
            if lp_str:
                try:
                    counts_map[t][1] += int(lp_str)
                except ValueError:
                    pass

    return counts_map
def get_task_daily_count(user_id, task_name, target_date=None):
    target_str = target_date.strftime("%d-%m-%Y") if target_date else datetime.now().strftime("%d-%m-%Y")
    cache_key = f"{user_id}_{task_name}_{target_str}"
    current_time = datetime.now().timestamp()

    if cache_key in _count_cache and cache_key in _count_cache_timestamp:
        if current_time - _count_cache_timestamp[cache_key] < 5:
            return _count_cache[cache_key]

    try:
        records = get_cached_records()
        count = 0

        if records:
            for record in records:
                record_user = str(record.get('User ID', '')).strip()
                record_task = str(record.get('Task', '')).strip()
                record_timestamp = str(record.get('Timestamp', '')).strip()

                if (record_user.lower() == user_id.strip().lower() and
                    record_task == task_name.strip() and
                    target_str in record_timestamp):
                    count += 1

        textbox_tasks = ["Load Transfer:", "Load Audit:", "Shipping:", "Allocation/Backorders:"]
        if task_name in textbox_tasks:
            try:
                records2 = get_cached_records(force_refresh=False, sheet_name=SHEET2_NAME)
                if records2:
                    for record in records2:
                        record_user = str(record.get('User ID', '')).strip()
                        record_task = str(record.get('Task', '')).strip()
                        record_timestamp = str(record.get('Timestamp', '')).strip()

                        if (record_user.lower() == user_id.strip().lower() and
                            record_task == task_name.strip() and
                            target_str in record_timestamp):
                            count += 1
            except Exception:
                pass

        _count_cache[cache_key] = count
        _count_cache_timestamp[cache_key] = current_time
        return count
    except Exception as e:
        print(f"Error getting count: {e}")
        return 0

def get_task_daily_load_sum(user_id, task_name, target_date=None):
    target_str = target_date.strftime("%d-%m-%Y") if target_date else datetime.now().strftime("%d-%m-%Y")
    cache_key = f"load_{user_id}_{task_name}_{target_str}"
    current_time = datetime.now().timestamp()

    if cache_key in _count_cache and cache_key in _count_cache_timestamp:
        if current_time - _count_cache_timestamp[cache_key] < 5:
            return _count_cache[cache_key]

    try:
        total_loads = 0
        textbox_tasks = ["Load Transfer:", "Load Audit:", "Shipping:", "Allocation/Backorders:"]
        if task_name in textbox_tasks:
            try:
                records2 = get_cached_records(force_refresh=False, sheet_name=SHEET2_NAME)
                if records2:
                    for record in records2:
                        record_user = str(record.get('User ID', '')).strip()
                        record_task = str(record.get('Task', '')).strip()
                        record_timestamp = str(record.get('Timestamp', '')).strip()

                        if (record_user.lower() == user_id.strip().lower() and
                            record_task == task_name.strip() and
                            target_str in record_timestamp):
                            load_id = str(record.get('Load ID', '')).strip()
                            if load_id and load_id != '':
                                try:
                                    total_loads += int(load_id)
                                except Exception:
                                    pass
            except Exception:
                pass

        _count_cache[cache_key] = total_loads
        _count_cache_timestamp[cache_key] = current_time
        return total_loads
    except Exception as e:
        print(f"Error getting load sum: {e}")
        return 0

def get_task_daily_lp_sum(user_id, task_name, target_date=None):
    target_str = target_date.strftime("%d-%m-%Y") if target_date else datetime.now().strftime("%d-%m-%Y")
    cache_key = f"lp_{user_id}_{task_name}_{target_str}"
    current_time = datetime.now().timestamp()

    if cache_key in _count_cache and cache_key in _count_cache_timestamp:
        if current_time - _count_cache_timestamp[cache_key] < 5:
            return _count_cache[cache_key]

    try:
        total_lp = 0
        textbox_tasks = ["Load Transfer:", "Load Audit:", "Shipping:", "Allocation/Backorders:"]
        if task_name in textbox_tasks:
            try:
                records2 = get_cached_records(force_refresh=False, sheet_name=SHEET2_NAME)
                if records2:
                    for record in records2:
                        record_user = str(record.get('User ID', '')).strip()
                        record_task = str(record.get('Task', '')).strip()
                        record_timestamp = str(record.get('Timestamp', '')).strip()

                        if (record_user.lower() == user_id.strip().lower() and
                            record_task == task_name.strip() and
                            target_str in record_timestamp):
                            lp_count = str(record.get('LP Count', '')).strip()
                            if lp_count and lp_count != '':
                                try:
                                    total_lp += int(lp_count)
                                except Exception:
                                    pass
            except Exception:
                pass

        _count_cache[cache_key] = total_lp
        _count_cache_timestamp[cache_key] = current_time
        return total_lp
    except Exception as e:
        print(f"Error getting LP sum: {e}")
        return 0

def check_duplicate(task, job_id, job_status):
    try:
        records = get_cached_records()
        if not records:
            return False, None
        for record in records:
            record_task = str(record.get('Task', '')).strip()
            record_job_id = str(record.get('Job ID', '')).strip()
            record_job_status = str(record.get('Job Status', '')).strip()
            record_user_id = str(record.get('User ID', '')).strip()

            if (record_task.lower() == task.strip().lower() and
                record_job_id.lower() == job_id.strip().lower() and
                record_job_status.lower() == job_status.strip().lower()):
                return True, record_user_id
        return False, None
    except Exception as e:
        print(f"Error checking duplicates: {e}")
        return False, None

def check_duplicate_sheet2(task, job_id, load_id, lp_count):
    try:
        records = get_cached_records(force_refresh=False, sheet_name=SHEET2_NAME)
        if not records:
            return False, None
        for record in records:
            record_task = str(record.get('Task', '')).strip()
            record_job_id = str(record.get('Job ID', '')).strip()
            record_load_id = str(record.get('Load ID', '')).strip()
            record_lp_count = str(record.get('LP Count', '')).strip()
            record_user_id = str(record.get('User ID', '')).strip()

            if (record_task.lower() == task.strip().lower() and
                record_job_id.lower() == job_id.strip().lower() and
                record_load_id == load_id.strip() and
                record_lp_count == lp_count.strip()):
                return True, record_user_id
        return False, None
    except Exception as e:
        print(f"Error checking duplicates in Sheet2: {e}")
        return False, None

def save_to_sheet(task, job_id, job_status, user_id):
    try:
        sheet, msg = connect_to_sheets()
        if not sheet:
            add_activity_log("TASK", f"Submit failed (Offline): {task.rstrip(':')} -> Job: {job_id}", "ERROR", msg)
            return False, msg, None
        is_duplicate, existing_user = check_duplicate(task, job_id, job_status)
        if is_duplicate:
            add_activity_log("TASK", f"Duplicate submit blocked: {task.rstrip(':')} -> Job: {job_id} (Assigned to {existing_user})", "WARN")
            return False, f"Already assigned to {existing_user}", existing_user

        timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        data_row = [timestamp, task, job_id, job_status, user_id]

        sheet.append_row(data_row)
        global _records_cache
        if _records_cache is not None:
            _records_cache.append({
                'Timestamp': timestamp,
                'Task': task,
                'Job ID': job_id,
                'Job Status': job_status,
                'User ID': user_id
            })
            _save_local_disk_cache()
            _count_cache.clear()
        else:
            invalidate_cache("sheet1")
        add_activity_log("TASK", f"Submitted '{task.rstrip(':')}' | Job: {job_id} | Status: {job_status} ({user_id})", "SUCCESS")
        return True, "Saved successfully!", None
    except Exception as e:
        print(f"Error saving: {e}")
        add_activity_log("TASK", f"Submit exception: {task.rstrip(':')} -> Job: {job_id}: {e}", "ERROR")
        return False, str(e), None

def save_to_sheet2(task, job_id, load_id, lp_count, user_id):
    try:
        sheet, msg = connect_to_sheets(force_refresh=False, sheet_name=SHEET2_NAME)
        if not sheet:
            add_activity_log("TASK", f"Submit failed (Offline): {task.rstrip(':')} -> Job: {job_id}", "ERROR", msg)
            return False, msg, None
        is_duplicate, existing_user = check_duplicate_sheet2(task, job_id, load_id, lp_count)
        if is_duplicate:
            add_activity_log("TASK", f"Duplicate submit blocked: {task.rstrip(':')} -> Job: {job_id} (Assigned to {existing_user})", "WARN")
            return False, f"Already assigned to {existing_user}", existing_user

        timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        data_row = [timestamp, task, job_id, load_id, lp_count, user_id]

        sheet.append_row(data_row)
        global _records2_cache
        if _records2_cache is not None:
            _records2_cache.append({
                'Timestamp': timestamp,
                'Task': task,
                'Job ID': job_id,
                'Load ID': load_id,
                'LP Count': lp_count,
                'User ID': user_id
            })
            _save_local_disk_cache()
            _count_cache.clear()
        else:
            invalidate_cache(SHEET2_NAME)
        add_activity_log("TASK", f"Submitted '{task.rstrip(':')}' | Job: {job_id} | Loads: {load_id} | LPs: {lp_count} ({user_id})", "SUCCESS")
        return True, "Saved successfully!", None
    except Exception as e:
        print(f"Error saving to Sheet2: {e}")
        add_activity_log("TASK", f"Submit exception: {task.rstrip(':')} -> Job: {job_id}: {e}", "ERROR")
        return False, str(e), None

def delete_from_sheet(task, job_id, job_status, user_id):
    try:
        sheet, msg = connect_to_sheets()
        if not sheet:
            add_activity_log("TASK", f"Delete failed (Offline): {task.rstrip(':')} -> Job: {job_id}", "ERROR", msg)
            return False, "Connection failed: " + str(msg)
        records = get_cached_records(force_refresh=False)
        if not records:
            return False, "No data found to delete"

        row_to_delete = None
        record_to_remove = None
        for i, record in enumerate(records, start=2):
            record_task = str(record.get('Task', '')).strip()
            record_job_id = str(record.get('Job ID', '')).strip()
            record_job_status = str(record.get('Job Status', '')).strip()
            record_user_id = str(record.get('User ID', '')).strip()

            if (record_task.lower() == task.strip().lower() and
                record_job_id.lower() == job_id.strip().lower() and
                record_job_status.lower() == job_status.strip().lower() and
                record_user_id.lower() == user_id.strip().lower()):
                row_to_delete = i
                record_to_remove = record
                break

        if row_to_delete is None:
            add_activity_log("TASK", f"Delete failed: No matching record for Job {job_id} ({user_id})", "WARN")
            return False, "No matching record found for your User ID"

        try:
            sheet.delete_rows(row_to_delete)
        except AttributeError:
            sheet.delete_row(row_to_delete)

        global _records_cache
        if _records_cache and record_to_remove in _records_cache:
            _records_cache.remove(record_to_remove)
            _save_local_disk_cache()
            _count_cache.clear()
        else:
            invalidate_cache("sheet1")
        add_activity_log("TASK", f"Deleted '{task.rstrip(':')}' | Job: {job_id} | Status: {job_status} ({user_id})", "SUCCESS")
        return True, "Deleted successfully"
    except Exception as e:
        print(f"Error deleting: {e}")
        add_activity_log("TASK", f"Delete exception: {task.rstrip(':')} -> Job: {job_id}: {e}", "ERROR")
        return False, str(e)

def delete_from_sheet2(task, job_id, user_id):
    try:
        sheet, msg = connect_to_sheets(force_refresh=False, sheet_name=SHEET2_NAME)
        if not sheet:
            add_activity_log("TASK", f"Delete failed (Offline): {task.rstrip(':')} -> Job: {job_id}", "ERROR", msg)
            return False, "Connection failed: " + str(msg)
        records = get_cached_records(force_refresh=False, sheet_name=SHEET2_NAME)
        if not records:
            return False, "No data found to delete"

        row_to_delete = None
        record_to_remove = None
        for i, record in enumerate(records, start=2):
            record_task = str(record.get('Task', '')).strip()
            record_job_id = str(record.get('Job ID', '')).strip()
            record_user_id = str(record.get('User ID', '')).strip()

            if (record_task.lower() == task.strip().lower() and
                record_job_id.lower() == job_id.strip().lower() and
                record_user_id.lower() == user_id.strip().lower()):
                row_to_delete = i
                record_to_remove = record
                break

        if row_to_delete is None:
            add_activity_log("TASK", f"Delete failed: No matching record for Job {job_id} ({user_id})", "WARN")
            return False, "No matching record found for your User ID"

        try:
            sheet.delete_rows(row_to_delete)
        except AttributeError:
            sheet.delete_row(row_to_delete)

        global _records2_cache
        if _records2_cache and record_to_remove in _records2_cache:
            _records2_cache.remove(record_to_remove)
            _save_local_disk_cache()
            _count_cache.clear()
        else:
            invalidate_cache(SHEET2_NAME)
        add_activity_log("TASK", f"Deleted '{task.rstrip(':')}' | Job: {job_id} ({user_id})", "SUCCESS")
        return True, "Deleted successfully"
    except Exception as e:
        print(f"Error deleting from Sheet2: {e}")
        add_activity_log("TASK", f"Delete exception: {task.rstrip(':')} -> Job: {job_id}: {e}", "ERROR")
        return False, str(e)


# ==========================================
# SET APPEARANCE
# ==========================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Aurora Borealis palette — mirrors main_app.py
AURORA_CYAN      = "#00e5ff"
AURORA_CYAN_DARK = "#00c4d9"
AURORA_MINT      = "#49cf9e"
NAVY_BG          = "#0b1420"
NAVY_CARD        = "#0d1b2a"
NAVY_HOVER       = "#13233a"
NAVY_ACTIVE      = "#162e4c"
NAVY_BORDER      = "#142338"
NAVY_BTN         = "#1a3a5c"


# ==========================================
# MAIN APPLICATION CLASS
# ==========================================
class EFLApp:
    def __init__(self, root, container=None, standalone=True):
        self.root = root
        self.container = container if container is not None else root
        self.standalone = standalone

        if self.standalone:
            self.root.title("User Data Manager")
            self.root.geometry("785x650")
            self.root.resizable(False, False)
            self.root.protocol("WM_DELETE_WINDOW", self.close_app_safely)

        # Active User State
        self.current_user = None

        # Store current selected date
        self.selected_date = datetime.now().date()
        self.is_edit_mode_enabled = True
        self.is_first_load = True

        # Frame containers
        self.login_frame = None
        self.main_frame = None
        self.content_frame = None

        # Tracking for popup and timers
        self.popup = None
        self._outside_click_bind_id = None
        self.status_check_timer = None
        self.auto_refresh_timer = None
        self.message_timer = None

        # UI element collections
        self.count_labels = []
        self.all_task_names = []
        self.all_entries = []
        self.all_dropdowns = []
        self.all_buttons = []

        # Message and Status references
        self.message_label = None
        self.status_dot = None
        self.status_label = None
        self.status_pill = None
        self.connection_status = False
        self.is_loading = False
        self.activity_log_window = None
        self.last_latency_ms = None
        self.log_filter_category = "All Events"

        global _current_app_instance
        _current_app_instance = self

        # Disk cache already loaded at module level (line 269) — no second read needed

        # Check for remembered session
        remembered = get_remembered_user()
        if remembered:
            self.current_user = remembered
            self.show_dashboard()
        else:
            self.show_login_screen()
            # Only sync users in background if on login screen
            threading.Thread(target=self.initial_user_sync, daemon=True).start()

    def initial_user_sync(self):
        """Silently sync user hashes from Sheet3 in the background on startup and reflect additions/removals"""
        try:
            sync_users_with_sheet3()
            if self.login_frame and hasattr(self, 'login_user_combo') and self.login_user_combo.winfo_exists():
                users = get_registered_users()
                combo_values = users if users else [""]
                cur_val = self.login_user_combo.get()
                new_val = cur_val if cur_val in combo_values else (combo_values[0] if combo_values else "")
                self.root.after(0, lambda: [
                    self.login_user_combo.configure(values=combo_values),
                    self.login_user_combo.set(new_val)
                ])
        except Exception as e:
            print(f"Background user sync error: {e}")

    # ==========================================================
    # LOGIN / AUTHENTICATION VIEW
    # ==========================================================
    def show_login_screen(self):
        """Build and display the modern Login / Registration screen"""
        if self.standalone:
            self.root.title("User Data Manager - Login")
        self.cancel_all_timers()

        self.all_entries = []
        self.all_dropdowns = []
        self.all_buttons = []
        self.count_labels = []
        self.all_task_names = []

        if self.main_frame:
            self.main_frame.destroy()
            self.main_frame = None

        if self.login_frame:
            self.login_frame.destroy()

        self.login_frame = ctk.CTkFrame(self.container, fg_color="#0b1420")
        self.login_frame.pack(fill=ctk.BOTH, expand=True)

        # Center Card Container
        center_container = ctk.CTkFrame(self.login_frame, fg_color="transparent")
        center_container.place(relx=0.5, rely=0.5, anchor="center")

        # Header Brand Banner
        header_card = ctk.CTkFrame(center_container, fg_color="#00e5ff", height=65, corner_radius=10, width=440)
        header_card.pack(fill=ctk.X, pady=(0, 15))
        header_card.pack_propagate(False)

        ctk.CTkLabel(
            header_card,
            text="USER DATA MANAGER",
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color="#0b1420"
        ).pack(expand=True)

        # Card Frame with border
        card = ctk.CTkFrame(
            center_container,
            fg_color="#0d1b2a",
            corner_radius=12,
            border_width=1,
            border_color="#142338",
            width=440,
            height=430
        )
        card.pack(fill=ctk.BOTH, expand=True)
        card.pack_propagate(False)

        # Tabview for Sign In and Register
        self.auth_tabview = ctk.CTkTabview(
            card,
            width=410,
            height=370,
            segmented_button_selected_color="#00e5ff",
            segmented_button_selected_hover_color="#00c4d9",
            segmented_button_unselected_color="#13233a",
            segmented_button_unselected_hover_color="#162e4c",
            fg_color="#0d1b2a",
            text_color="#ffffff",
            segmented_button_fg_color="#13233a"
        )
        self.auth_tabview.pack(padx=15, pady=(10, 10), fill=ctk.BOTH, expand=True)

        tab_login = self.auth_tabview.add("Sign In")
        tab_register = self.auth_tabview.add("Register User")

        # --- SIGN IN TAB ---
        ctk.CTkLabel(
            tab_login,
            text="User ID",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        ).pack(anchor="w", padx=15, pady=(10, 3))

        registered_users = get_registered_users()
        default_user_val = registered_users[0] if registered_users else ""

        self.login_user_combo = ctk.CTkComboBox(
            tab_login,
            values=registered_users if registered_users else [""],
            height=34,
            corner_radius=6,
            fg_color="#13233a",
            border_color="#142338",
            text_color="#ffffff",
            dropdown_fg_color="#0d1b2a",
            dropdown_text_color="#ffffff",
            dropdown_hover_color="#162e4c"
        )
        self.login_user_combo.set(default_user_val)
        self.login_user_combo.pack(fill=ctk.X, padx=15, pady=(0, 10))

        ctk.CTkLabel(
            tab_login,
            text="Password",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        ).pack(anchor="w", padx=15, pady=(0, 3))

        pwd_row = ctk.CTkFrame(tab_login, fg_color="transparent")
        pwd_row.pack(fill=ctk.X, padx=15, pady=(0, 8))

        self.login_pass_entry = ctk.CTkEntry(
            pwd_row,
            show="•",
            height=34,
            corner_radius=6,
            fg_color="#13233a",
            border_color="#142338",
            text_color="#ffffff",
            placeholder_text_color="#64748b",
            placeholder_text="Enter password"
        )
        self.login_pass_entry.pack(side=ctk.LEFT, fill=ctk.X, expand=True, padx=(0, 8))

        self.login_show_pwd = False
        def toggle_login_pwd():
            self.login_show_pwd = not self.login_show_pwd
            self.login_pass_entry.configure(show="" if self.login_show_pwd else "•")
            btn_show_pwd.configure(text="Hide" if self.login_show_pwd else "Show")

        btn_show_pwd = ctk.CTkButton(
            pwd_row,
            text="Show",
            width=55,
            height=34,
            corner_radius=6,
            fg_color="#13233a",
            hover_color="#162e4c",
            text_color="#e2e8f0",
            font=ctk.CTkFont(size=11),
            command=toggle_login_pwd
        )
        btn_show_pwd.pack(side=ctk.RIGHT)

        # Remember Me Checkbox
        self.remember_var = ctk.BooleanVar(value=True)
        remember_cb = ctk.CTkCheckBox(
            tab_login,
            text="Remember Login on this device",
            variable=self.remember_var,
            font=ctk.CTkFont(size=11),
            fg_color="#00e5ff",
            hover_color="#00c4d9",
            text_color="#e2e8f0",
            checkmark_color="#0b1420"
        )
        remember_cb.pack(anchor="w", padx=15, pady=(0, 12))

        # Login Status / Error Message
        self.login_msg_label = ctk.CTkLabel(
            tab_login,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f44336"
        )
        self.login_msg_label.pack(pady=(0, 8))

        # Sign In Button
        btn_sign_in = ctk.CTkButton(
            tab_login,
            text="Sign In",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            corner_radius=6,
            fg_color="#00e5ff",
            hover_color="#00c4d9",
            text_color="#0b1420",
            command=self.handle_login
        )
        btn_sign_in.pack(fill=ctk.X, padx=15, pady=(0, 5))

        # Bind Enter Key
        self.login_user_combo.bind("<Return>", lambda e: self.handle_login())
        self.login_pass_entry.bind("<Return>", lambda e: self.handle_login())

        # --- REGISTER TAB ---
        ctk.CTkLabel(
            tab_register,
            text="New User ID",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        ).pack(anchor="w", padx=15, pady=(5, 2))

        self.reg_user_entry = ctk.CTkEntry(
            tab_register,
            height=32,
            corner_radius=6,
            fg_color="#13233a",
            border_color="#142338",
            text_color="#ffffff",
            placeholder_text_color="#64748b",
            placeholder_text="e.g. Akash, Chamara, John"
        )
        self.reg_user_entry.pack(fill=ctk.X, padx=15, pady=(0, 6))

        ctk.CTkLabel(
            tab_register,
            text="New Password",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        ).pack(anchor="w", padx=15, pady=(0, 2))

        self.reg_pass_entry = ctk.CTkEntry(
            tab_register,
            show="•",
            height=32,
            corner_radius=6,
            fg_color="#13233a",
            border_color="#142338",
            text_color="#ffffff",
            placeholder_text_color="#64748b",
            placeholder_text="Enter password"
        )
        self.reg_pass_entry.pack(fill=ctk.X, padx=15, pady=(0, 6))

        ctk.CTkLabel(
            tab_register,
            text="Confirm Password",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        ).pack(anchor="w", padx=15, pady=(0, 2))

        self.reg_confirm_entry = ctk.CTkEntry(
            tab_register,
            show="•",
            height=32,
            corner_radius=6,
            fg_color="#13233a",
            border_color="#142338",
            text_color="#ffffff",
            placeholder_text_color="#64748b",
            placeholder_text="Re-enter password"
        )
        self.reg_confirm_entry.pack(fill=ctk.X, padx=15, pady=(0, 8))

        self.reg_msg_label = ctk.CTkLabel(
            tab_register,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f44336"
        )
        self.reg_msg_label.pack(pady=(0, 6))

        btn_register = ctk.CTkButton(
            tab_register,
            text="Create User Account",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            corner_radius=6,
            fg_color="#4CAF50",
            hover_color="#45a049",
            text_color="white",
            command=self.handle_register
        )
        btn_register.pack(fill=ctk.X, padx=15, pady=(0, 5))

        self.reg_user_entry.bind("<Return>", lambda e: self.handle_register())
        self.reg_pass_entry.bind("<Return>", lambda e: self.handle_register())
        self.reg_confirm_entry.bind("<Return>", lambda e: self.handle_register())

        # Focus on user selection / entry
        def safe_focus():
            try:
                if hasattr(self, 'login_user_combo') and self.login_user_combo.winfo_exists():
                    self.login_user_combo.focus_set()
            except Exception:
                pass
        self.root.after(100, safe_focus)

    def handle_login(self):
        username = self.login_user_combo.get().strip()
        password = self.login_pass_entry.get().strip()
        remember = self.remember_var.get()

        if not username:
            self.login_msg_label.configure(text="Please select or enter a User ID", text_color="#f44336")
            return

        if not password:
            self.login_msg_label.configure(text="Please enter password", text_color="#f44336")
            return

        success, result = authenticate_user(username, password)
        if success:
            actual_username = result
            set_remembered_user(actual_username, remember=remember)
            self.current_user = actual_username
            self.login_msg_label.configure(text="Login successful! Loading...", text_color="#4CAF50")
            self.root.after(200, self.show_dashboard)
        else:
            self.login_msg_label.configure(text=result, text_color="#f44336")

    def handle_register(self):
        username = self.reg_user_entry.get().strip()
        password = self.reg_pass_entry.get().strip()
        confirm = self.reg_confirm_entry.get().strip()

        if not username:
            self.reg_msg_label.configure(text="User ID cannot be blank", text_color="#f44336")
            return

        if password != confirm:
            self.reg_msg_label.configure(text="Passwords do not match", text_color="#f44336")
            return

        success, msg = register_user(username, password, sync_remote=True)
        if success:
            self.reg_msg_label.configure(text=msg, text_color="#4CAF50")
            # Update user combo in login tab
            updated_users = get_registered_users()
            self.login_user_combo.configure(values=updated_users)
            self.login_user_combo.set(username)
            self.login_pass_entry.delete(0, "end")
            self.login_pass_entry.insert(0, password)
            def switch_to_sign_in():
                try:
                    if hasattr(self, 'auth_tabview') and self.auth_tabview.winfo_exists():
                        self.auth_tabview.set("Sign In")
                    if hasattr(self, 'login_msg_label') and self.login_msg_label.winfo_exists():
                        self.login_msg_label.configure(text="Account created & encrypted hash saved to Sheet3! Click Sign In to continue", text_color="#4CAF50")
                except Exception:
                    pass
            self.root.after(800, switch_to_sign_in)
        else:
            self.reg_msg_label.configure(text=msg, text_color="#f44336")

    def logout(self):
        """Log out the current user, clear session, and show login screen"""
        set_remembered_user(None, remember=False)
        self.current_user = None
        self.close_popup_safely()
        self.all_entries = []
        self.all_dropdowns = []
        self.all_buttons = []
        self.count_labels = []
        self.all_task_names = []
        self.show_login_screen()

    def cancel_all_timers(self):
        """Cancel background polling and message timers"""
        if getattr(self, '_log_refresh_timer', None):
            try:
                self.root.after_cancel(self._log_refresh_timer)
            except Exception:
                pass
            self._log_refresh_timer = None

        if self.status_check_timer:
            try:
                self.root.after_cancel(self.status_check_timer)
            except Exception:
                pass
            self.status_check_timer = None

        if self.auto_refresh_timer:
            try:
                self.root.after_cancel(self.auto_refresh_timer)
            except Exception:
                pass
            self.auto_refresh_timer = None

        if self.message_timer:
            try:
                self.root.after_cancel(self.message_timer)
            except Exception:
                pass
            self.message_timer = None

    # ==========================================================
    # DASHBOARD VIEW
    # ==========================================================
    def show_dashboard(self):
        """Initialize and display the main User Data Manager dashboard"""
        if self.standalone:
            self.root.title(f"User Data Manager - [{self.current_user}]")

        if self.login_frame:
            self.login_frame.destroy()
            self.login_frame = None

        if self.main_frame:
            self.main_frame.destroy()

        # Main Container
        self.main_frame = ctk.CTkFrame(self.container, fg_color="#060d17")
        self.main_frame.pack(fill=ctk.BOTH, expand=True)

        # Scrollable container so it fits on any screen height/width
        self.content_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color="#060d17", scrollbar_button_color="#142236", scrollbar_button_hover_color="#1a2d47")
        self.content_frame.pack(fill=ctk.BOTH, expand=True, padx=24, pady=16)

        # Reset collections
        self.count_labels = []
        self.all_task_names = []
        self.all_entries = []
        self.all_dropdowns = []
        self.all_buttons = []
        self.selected_date = datetime.now().date()
        self.is_edit_mode_enabled = True
        self.is_first_load = True

        # Build lightweight header immediately (fast — no CTkScrollableFrame / buttons)
        self.setup_header(self.content_frame)
        self.setup_top_user_date_row(self.content_frame)

        # Reset inputs after layout is fully committed
        self.root.after(20, self.reset_all_inputs)

        # If cache is available, show counts as soon as sections are built
        _show_cached_counts = bool(_records_cache)

        # Build heavyweight sections progressively across event-loop ticks so the
        # header appears immediately and the rest populates without blocking the UI.
        def _build_section1():
            self.setup_section1(self.content_frame)
            self.root.after(0, _build_section2)

        def _build_section2():
            self.setup_section2(self.content_frame)
            self.root.after(0, _build_log)

        def _build_log():
            self.setup_live_activity_log(self.content_frame)
            self.setup_footer(self.content_frame)
            if _show_cached_counts:
                self.update_status(True)
                self.update_all_counts()
            # Load fresh data in background via fast single-batch API call
            self.root.after(0, self.load_data_background)
            # Start status check
            self.root.after(5000, self.check_connection_status)

        self.root.after(0, _build_section1)

    def load_data_background(self):
        """Load data in background thread using fast single-batch API call"""
        def load():
            success, msg = fetch_all_sheets_batch()
            if success:
                self.root.after(0, lambda: [self.show_message("Connected!", "success"), self.update_status(True)])
            else:
                if _records_cache:
                    self.root.after(0, lambda: [self.show_message("Working Offline (Cached)", "info"), self.update_status(True)])
                else:
                    self.root.after(0, lambda: [self.show_message(f"Connection Failed: {msg}", "error"), self.update_status(False)])

            self.root.after(0, self.update_all_counts)
            self.root.after(0, self.start_auto_refresh)
            self.root.after(0, self.update_edit_mode)
            self.root.after(0, lambda: setattr(self, 'is_first_load', False))

        threading.Thread(target=load, daemon=True).start()

    def start_auto_refresh(self):
        self.auto_refresh_timer = self.root.after(AUTO_REFRESH_INTERVAL, self.auto_refresh_counts)

    def close_app_safely(self):
        self.close_popup_safely()
        self.cancel_all_timers()
        if self.standalone:
            self.root.destroy()

    # ==========================================================
    # STATUS INDICATOR METHODS
    # ==========================================================
    def update_status(self, is_connected):
        self.connection_status = is_connected
        color = "#10b981" if is_connected else "#ef4444"
        if self.status_dot and self.status_dot.winfo_exists():
            self.status_dot.configure(fg_color=color)
        if self.status_label and self.status_label.winfo_exists():
            status_text = "Database connection synchronized" if is_connected else "Offline mode (cached)"
            self.status_label.configure(text=status_text)
        if hasattr(self, 'inline_status_badge') and self.inline_status_badge and self.inline_status_badge.winfo_exists():
            self.inline_status_badge.configure(
                text="● Online (Synced)" if is_connected else "● Offline (Cached)",
                text_color=color
            )
        if hasattr(self, 'inline_latency_label') and self.inline_latency_label and self.inline_latency_label.winfo_exists():
            lat_text = f"⚡ {self.last_latency_ms} ms" if getattr(self, 'last_latency_ms', None) else "⚡ -- ms"
            self.inline_latency_label.configure(text=lat_text)
        if hasattr(self, 'modal_status_badge') and self.modal_status_badge and self.modal_status_badge.winfo_exists():
            self.modal_status_badge.configure(
                text="● Connected" if is_connected else "● Offline (Cached)",
                text_color=color
            )

    def check_connection_status(self):
        def check():
            t0 = time.time()
            try:
                sheet, msg = connect_to_sheets()
                status = sheet is not None
                self.last_latency_ms = max(1, int((time.time() - t0) * 1000))
            except Exception:
                status = False
            prev_status = getattr(self, 'connection_status', None)
            if prev_status != status or not status:
                add_activity_log("CONNECTION", f"Heartbeat check: {'Online (Synchronized)' if status else 'Offline'}", "SUCCESS" if status else "WARN")
            self.root.after(0, lambda: self.update_status(status))

        threading.Thread(target=check, daemon=True).start()
        self.status_check_timer = self.root.after(30000, self.check_connection_status)

    # ==========================================================
    # MESSAGE DISPLAY
    # ==========================================================
    def show_message(self, message, msg_type="success"):
        if self.message_timer:
            self.root.after_cancel(self.message_timer)
            self.message_timer = None

        colors = {
            "success": "#4CAF50",
            "error": "#f44336",
            "warning": "#FF9800",
            "info": "#2196F3",
            "duplicate": "#FF6B00",
            "edit_enabled": "#4CAF50",
            "edit_disabled": "#f44336"
        }

        color = colors.get(msg_type, "#e0e0e0")

        if self.message_label and self.message_label.winfo_exists():
            self.message_label.configure(text=message, text_color=color)

        self.message_timer = self.root.after(3000, self.clear_message)

    def clear_message(self):
        if self.message_label and self.message_label.winfo_exists():
            self.message_label.configure(text="")
        if self.message_timer:
            self.message_timer = None

    # ==========================================================
    # RESET ALL INPUT FIELDS
    # ==========================================================
    def reset_all_inputs(self):
        """Reset all dropdowns to 'New' and clear all entry boxes"""
        for entry in self.all_entries:
            try:
                if entry.winfo_exists():
                    entry.delete(0, "end")
            except Exception as e:
                print(f"Error clearing entry: {e}")

        for dropdown in self.all_dropdowns:
            try:
                if dropdown.winfo_exists():
                    dropdown.set("New")
            except Exception as e:
                print(f"Error resetting dropdown: {e}")




    # ==========================================================
    # ==========================================================
    # UI SETUP METHODS
    # ==========================================================
    def setup_header(self, parent=None):
        p = parent if parent is not None else self.main_frame
        header_container = ctk.CTkFrame(p, fg_color="transparent")
        header_container.pack(fill=ctk.X, pady=(0, 16))

        # LEFT: Title & Subtitle
        title_box = ctk.CTkFrame(header_container, fg_color="transparent")
        title_box.pack(side=ctk.LEFT, anchor="w")

        ctk.CTkLabel(
            title_box,
            text="User Data Manager",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#ffffff",
            anchor="w"
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text="Configure reconciliations, load transfers, and data allocations",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#64748b",
            anchor="w"
        ).pack(anchor="w", pady=(2, 0))

        # RIGHT: Profile & Date Controls
        controls_box = ctk.CTkFrame(header_container, fg_color="transparent")
        controls_box.pack(side=ctk.RIGHT, anchor="e")

        # 1. User Profile Pill
        user_name = self.current_user or "User"
        initial = (user_name[0] if user_name else "U").upper()

        user_pill = ctk.CTkFrame(
            controls_box,
            fg_color="#0a121e",
            border_width=1,
            border_color="#182a44",
            corner_radius=8,
            height=34
        )
        user_pill.pack(side=ctk.RIGHT, padx=(10, 0))
        user_pill.pack_propagate(False)

        # Avatar circle
        avatar_frame = ctk.CTkFrame(
            user_pill,
            fg_color="#0284c7",
            corner_radius=11,
            width=22,
            height=22
        )
        avatar_frame.pack(side=ctk.LEFT, padx=(6, 6), pady=6)
        avatar_frame.pack_propagate(False)

        ctk.CTkLabel(
            avatar_frame,
            text=initial,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#ffffff"
        ).pack(expand=True)

        self.username_value = ctk.CTkLabel(
            user_pill,
            text=user_name,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#ffffff"
        )
        self.username_value.pack(side=ctk.LEFT, padx=(0, 8))

        logout_btn = ctk.CTkButton(
            user_pill,
            text="[→",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            width=22,
            height=22,
            corner_radius=4,
            fg_color="transparent",
            hover_color="#dc2626",
            text_color="#94a3b8",
            command=self.logout
        )
        logout_btn.pack(side=ctk.LEFT, padx=(0, 6))

        # 2. Date Selector Pill
        self.date_pill = ctk.CTkFrame(
            controls_box,
            fg_color="#0a121e",
            border_width=1,
            border_color="#182a44",
            corner_radius=8,
            height=34,
            cursor="hand2"
        )
        self.date_pill.pack(side=ctk.RIGHT)
        self.date_pill.pack_propagate(False)

        date_icon = ctk.CTkLabel(
            self.date_pill,
            text="🗓",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            cursor="hand2"
        )
        date_icon.pack(side=ctk.LEFT, padx=(8, 5))

        self.date_label = ctk.CTkLabel(
            self.date_pill,
            text=self.selected_date.strftime("%d-%m-%Y"),
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#ffffff",
            cursor="hand2"
        )
        self.date_label.pack(side=ctk.LEFT, padx=(0, 5))

        self.date_arrow = ctk.CTkLabel(
            self.date_pill,
            text="▼",
            font=ctk.CTkFont(size=8),
            text_color="#64748b",
            cursor="hand2"
        )
        self.date_arrow.pack(side=ctk.LEFT, padx=(0, 8))

        # Bindings for calendar popup
        for w in (self.date_pill, date_icon, self.date_label, self.date_arrow):
            w.bind("<Button-1>", lambda e: self.toggle_dropdown_popup())

        # CENTER: Message Banner (Inline Toast)
        self.message_label = ctk.CTkLabel(
            header_container,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#10b981",
            anchor="center"
        )
        self.message_label.pack(side=ctk.LEFT, expand=True, padx=10)

    def setup_top_user_date_row(self, parent=None):
        pass  # Integrated into setup_header

    def toggle_dropdown_popup(self):
        if self.popup is not None and self.popup.winfo_exists():
            self.close_popup_safely()
            return

        self.popup = ctk.CTkToplevel(self.root)
        self.popup.overrideredirect(True)
        self.popup.geometry("240x310")
        self.popup.transient(self.root)

        self.position_popup()
        self.root.bind("<Configure>", self.position_popup)

        current_year = self.selected_date.year
        current_month = self.selected_date.month

        def select_date(year, month, day):
            try:
                self.selected_date = datetime(year, month, day).date()
                self.date_label.configure(text=self.selected_date.strftime("%d-%m-%Y"))
                self.close_popup_safely()

                today = datetime.now().date()

                if self.selected_date == today:
                    self.reset_all_inputs()
                    self.show_message("Edit mode enabled", "edit_enabled")
                else:
                    self.show_message("Edit mode disabled", "edit_disabled")

                self.update_all_counts()
                self.update_edit_mode()
                self.root.focus_force()
            except ValueError:
                pass

        def build_calendar(year, month):
            for widget in popup_frame.winfo_children():
                widget.destroy()

            nav_container = ctk.CTkFrame(popup_frame, fg_color="#101c2e", corner_radius=6, height=34)
            nav_container.pack(fill=ctk.X, pady=(10, 8), padx=6)
            nav_container.pack_propagate(False)

            prev_btn = ctk.CTkButton(
                nav_container, text="◀", width=30, height=26, fg_color="#162a45",
                text_color="#ffffff", hover_color="#1e3a5f", corner_radius=4, font=ctk.CTkFont(size=12),
                command=lambda: navigate_month(-1)
            )
            prev_btn.pack(side=ctk.LEFT, padx=(6, 4))

            month_year_label = ctk.CTkLabel(
                nav_container, text=f"{calendar.month_name[month]} {year}",
                font=ctk.CTkFont(size=13, weight="bold"), text_color="#ffffff"
            )
            month_year_label.pack(side=ctk.LEFT, expand=True)

            next_btn = ctk.CTkButton(
                nav_container, text="▶", width=30, height=26, fg_color="#162a45",
                text_color="#ffffff", hover_color="#1e3a5f", corner_radius=4, font=ctk.CTkFont(size=12),
                command=lambda: navigate_month(1)
            )
            next_btn.pack(side=ctk.RIGHT, padx=(4, 6))

            day_frame = ctk.CTkFrame(popup_frame, fg_color="transparent")
            day_frame.pack(fill=ctk.X, pady=(0, 3))
            day_names = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
            for day in day_names:
                ctk.CTkLabel(
                    day_frame, text=day, font=ctk.CTkFont(size=9, weight="bold"),
                    text_color="#94a3b8", width=30, anchor="center"
                ).pack(side=ctk.LEFT, padx=1)

            cal = calendar.monthcalendar(year, month)
            today = datetime.now().date()
            grid_container = ctk.CTkFrame(popup_frame, fg_color="transparent")
            grid_container.pack(fill=ctk.X, pady=2, padx=8)

            for week in cal:
                week_frame = ctk.CTkFrame(grid_container, fg_color="transparent")
                week_frame.pack(fill=ctk.X, pady=1)
                for day in week:
                    if day == 0:
                        ctk.CTkLabel(week_frame, text="", width=30).pack(side=ctk.LEFT, padx=1)
                    else:
                        date_obj = datetime(year, month, day).date()
                        is_today = (date_obj == today)
                        is_selected = (date_obj == self.selected_date)
                        is_future = (date_obj > today)

                        btn = ctk.CTkButton(
                            week_frame, text=str(day), width=30, height=26,
                            font=ctk.CTkFont(size=10, weight="bold"),
                            fg_color="#00e5ff" if is_selected else ("#10b981" if is_today else ("#101c2e" if not is_future else "#08101c")),
                            text_color="#060d17" if (is_selected or is_today) else ("#ffffff" if not is_future else "#475569"),
                            hover_color="#00c4d9" if not is_future else "#08101c",
                            state="disabled" if is_future else "normal",
                            command=lambda d=day: select_date(year, month, d)
                        )
                        btn.pack(side=ctk.LEFT, padx=1)

            bottom_frame = ctk.CTkFrame(popup_frame, fg_color="transparent")
            bottom_frame.pack(fill=ctk.X, pady=(10, 10))
            today_btn = ctk.CTkButton(
                bottom_frame, text="Today", font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#10b981", hover_color="#059669", height=26, width=65, text_color="#060d17",
                command=lambda: select_date(today.year, today.month, today.day)
            )
            today_btn.pack(side=ctk.LEFT, padx=(6, 0))
            close_btn = ctk.CTkButton(
                bottom_frame, text="Close", font=ctk.CTkFont(size=10), fg_color="#ef4444",
                hover_color="#dc2626", height=26, width=65, command=self.close_popup_safely
            )
            close_btn.pack(side=ctk.RIGHT, padx=(0, 6))

        def navigate_month(delta):
            nonlocal current_year, current_month
            current_month += delta
            if current_month > 12:
                current_month = 1
                current_year += 1
            elif current_month < 1:
                current_month = 12
                current_year -= 1
            build_calendar(current_year, current_month)

        popup_frame = ctk.CTkFrame(self.popup, fg_color="#0c182b", corner_radius=6, border_width=1, border_color="#182a44")
        popup_frame.pack(fill=ctk.BOTH, expand=True)
        build_calendar(current_year, current_month)

        def on_global_click(event):
            if self.popup is not None and self.popup.winfo_exists():
                try:
                    px = self.popup.winfo_rootx()
                    py = self.popup.winfo_rooty()
                    pw = self.popup.winfo_width()
                    ph = self.popup.winfo_height()
                    if not (px <= event.x_root <= px + pw and py <= event.y_root <= py + ph):
                        target = getattr(self, 'date_pill', self.date_label)
                        dlx = target.winfo_rootx()
                        dly = target.winfo_rooty()
                        dlw = target.winfo_width() + 20
                        dlh = target.winfo_height()
                        if not (dlx <= event.x_root <= dlx + dlw and dly <= event.y_root <= dly + dlh):
                            self.close_popup_safely()
                except Exception:
                    self.close_popup_safely()

        self._outside_click_bind_id = self.root.bind_all("<Button-1>", on_global_click, add="+")

    def close_popup_safely(self):
        if self._outside_click_bind_id:
            try:
                self.root.unbind_all("<Button-1>")
            except Exception:
                pass
            self._outside_click_bind_id = None
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()
            self.popup = None

    def position_popup(self, event=None):
        if self.popup is not None and self.popup.winfo_exists():
            try:
                target = getattr(self, 'date_pill', self.date_label)
                x = target.winfo_rootx() - 70
                y = target.winfo_rooty() + 38
                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()
                popup_width = 240
                popup_height = 310

                if x + popup_width > screen_width:
                    x = screen_width - popup_width - 10
                if x < 10:
                    x = 10
                if y + popup_height > screen_height:
                    y = target.winfo_rooty() - popup_height - 10
                self.popup.geometry(f"+{int(x)}+{int(y)}")
            except Exception:
                pass

    def update_edit_mode(self):
        """Enable or disable UI elements based on whether selected date is today"""
        if not self.main_frame or not self.main_frame.winfo_exists():
            return
        today = datetime.now().date()
        is_today = self.selected_date == today
        state_val = "normal" if is_today else "disabled"

        for entry in self.all_entries:
            try:
                if entry.winfo_exists():
                    entry.configure(state=state_val)
            except Exception:
                pass

        for dropdown in self.all_dropdowns:
            try:
                if dropdown.winfo_exists():
                    dropdown.configure(state=state_val)
            except Exception:
                pass

        for button in self.all_buttons:
            try:
                if button.winfo_exists():
                    button.configure(state=state_val)
            except Exception:
                pass

        self.is_edit_mode_enabled = is_today

    def update_all_counts(self):
        """Update count labels for all tasks asynchronously to keep UI responsive"""
        if not self.main_frame or not self.main_frame.winfo_exists():
            return
        user_id = self.current_user or (self.username_value.cget("text") if self.username_value and self.username_value.winfo_exists() else "")
        if not user_id:
            return
        target_date = self.selected_date

        def fetch_and_update():
            counts_map = calculate_all_task_counts(user_id, target_date)
            counts = []
            for task_name in self.all_task_names:
                val = counts_map.get(task_name)
                if isinstance(val, list):
                    counts.append(f"{val[0]} - {val[1]}")
                elif val is not None:
                    counts.append(f"{val}")
                else:
                    counts.append("0")

            def apply_counts():
                for i, count_text in enumerate(counts):
                    if i < len(self.count_labels) and self.count_labels[i].winfo_exists():
                        self.count_labels[i].configure(text=count_text)

            self.root.after(0, apply_counts)

        threading.Thread(target=fetch_and_update, daemon=True).start()

    def auto_refresh_counts(self):
        if not getattr(self, 'is_loading', False) and self.current_user and self.main_frame and self.main_frame.winfo_exists():
            self.update_all_counts()
        self.auto_refresh_timer = self.root.after(AUTO_REFRESH_INTERVAL, self.auto_refresh_counts)

    def setup_section1(self, parent=None):
        p = parent if parent is not None else self.main_frame
        section_frame = ctk.CTkFrame(p, fg_color="#0a121e", corner_radius=10, border_width=1, border_color="#142236")
        section_frame.pack(pady=(0, 12), fill=ctk.X)

        # Table Column Headers
        col_header = ctk.CTkFrame(section_frame, fg_color="transparent")
        col_header.pack(fill=ctk.X, padx=16, pady=(10, 6))

        ctk.CTkLabel(col_header, text="Process Name", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=180, anchor="w").pack(side=ctk.LEFT, padx=(0, 10))
        ctk.CTkLabel(col_header, text="Reference / Batch Identifier", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=250, anchor="w").pack(side=ctk.LEFT, padx=(0, 10))
        ctk.CTkLabel(col_header, text="Category Filter", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=130, anchor="w").pack(side=ctk.LEFT, padx=(0, 15))
        ctk.CTkLabel(col_header, text="Counter", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=50, anchor="center").pack(side=ctk.LEFT, padx=(0, 15))
        ctk.CTkLabel(col_header, text="Actions", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=105, anchor="center").pack(side=ctk.LEFT)

        # Task Rows
        tasks_config = [
            ("GDN Reconciliation", "GDN Reconciliation:", "Enter GDN Identifier..."),
            ("GRN Reconciliation", "GRN Reconciliation:", "Enter GRN Identifier..."),
            ("GDN Creation", "GDN Creation:", "Enter Order Ref..."),
            ("GRN Creation", "GRN Creation:", "Enter Inbound Batch..."),
            ("Load Plan or ASN", "Load Plan or Asn:", "Enter ASN Number...")
        ]
        for display_name, task_key, placeholder in tasks_config:
            self.create_dropdown_row(section_frame, display_name, task_key, placeholder)

        ctk.CTkFrame(section_frame, fg_color="transparent", height=6).pack()

    def create_dropdown_row(self, parent, display_name, task_key, placeholder):
        self.all_task_names.append(task_key)

        row_frame = ctk.CTkFrame(parent, fg_color="transparent", height=38)
        row_frame.pack(fill=ctk.X, padx=16, pady=3)
        row_frame.pack_propagate(False)

        # Process Name
        ctk.CTkLabel(
            row_frame, text=display_name, font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#f1f5f9", width=180, anchor="w"
        ).pack(side=ctk.LEFT, padx=(0, 10))

        # Identifier Entry
        entry = ctk.CTkEntry(
            row_frame, font=ctk.CTkFont(family="Segoe UI", size=11), width=250, height=32, corner_radius=6,
            border_width=1, fg_color="#060d17", border_color="#182a44", text_color="#ffffff",
            placeholder_text_color="#475569", placeholder_text=placeholder
        )
        entry.pack(side=ctk.LEFT, padx=(0, 10))
        self.all_entries.append(entry)

        # Category Dropdown
        options = ["New", "Revise", "Separate"]
        if task_key in ["GDN Reconciliation:", "GRN Reconciliation:", "Load Plan or Asn:"]:
            options = ["New", "Revise"]

        dropdown = ctk.CTkOptionMenu(
            row_frame, values=options, font=ctk.CTkFont(family="Segoe UI", size=11), width=130, height=32,
            corner_radius=6, fg_color="#060d17", button_color="#0d1b2a",
            button_hover_color="#162e4c", text_color="#ffffff",
            dropdown_fg_color="#0c182b", dropdown_text_color="#ffffff",
            dropdown_hover_color="#162e4c"
        )
        dropdown.pack(side=ctk.LEFT, padx=(0, 15))
        dropdown.set("New")
        self.all_dropdowns.append(dropdown)

        # Counter Badge
        count_container = ctk.CTkFrame(row_frame, fg_color="#060d17", border_width=1, border_color="#182a44", corner_radius=6, width=50, height=30)
        count_container.pack(side=ctk.LEFT, padx=(0, 15))
        count_container.pack_propagate(False)

        count_label = ctk.CTkLabel(
            count_container, text="0", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#ffffff"
        )
        count_label.pack(expand=True)
        self.count_labels.append(count_label)

        # Actions
        actions_frame = ctk.CTkFrame(row_frame, fg_color="transparent", width=105, height=32)
        actions_frame.pack(side=ctk.LEFT)
        actions_frame.pack_propagate(False)

        submit_btn = ctk.CTkButton(
            actions_frame, text="Submit", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), width=60,
            height=30, corner_radius=6, fg_color="#059669", hover_color="#047857", text_color="#ffffff",
            command=lambda: self.submit_action_sheet1(entry, dropdown, task_key)
        )
        submit_btn.pack(side=ctk.LEFT, padx=(0, 6))
        self.all_buttons.append(submit_btn)

        delete_btn = ctk.CTkButton(
            actions_frame, text="🗑", font=ctk.CTkFont(family="Segoe UI", size=12), width=32,
            height=30, corner_radius=6, fg_color="#101c2e", hover_color="#dc2626", border_width=1, border_color="#182a44",
            text_color="#94a3b8",
            command=lambda: self.delete_action_sheet1(entry, dropdown, task_key)
        )
        delete_btn.pack(side=ctk.LEFT)
        self.all_buttons.append(delete_btn)

    def submit_action_sheet1(self, entry, dropdown, label_text):
        if not self.is_edit_mode_enabled:
            self.show_message("Edit mode disabled for past dates", "warning")
            return

        job_id = entry.get().strip()
        job_status = dropdown.get()
        user_id = self.current_user or (self.username_value.cget("text") if self.username_value and self.username_value.winfo_exists() else "")

        if not job_id or not job_status:
            self.show_message("Enter Job ID & Status", "warning")
            return

        self.show_message("Saving...", "info")

        def task_thread():
            success, msg, _ = save_to_sheet(label_text, job_id, job_status, user_id)

            def update_ui():
                if success:
                    entry.delete(0, "end")
                    dropdown.set("New")
                    self.update_all_counts()
                    self.show_message("Saved!", "success")
                    self.update_status(True)
                else:
                    if "Already assigned" in msg:
                        self.show_message(msg, "duplicate")
                    else:
                        self.show_message(msg, "error")
                        self.update_status(False)

            self.root.after(0, update_ui)

        threading.Thread(target=task_thread, daemon=True).start()

    def delete_action_sheet1(self, entry, dropdown, label_text):
        if not self.is_edit_mode_enabled:
            self.show_message("Edit mode disabled for past dates", "warning")
            return

        job_id = entry.get().strip()
        job_status = dropdown.get()
        user_id = self.current_user or (self.username_value.cget("text") if self.username_value and self.username_value.winfo_exists() else "")

        if not job_id or not job_status:
            self.show_message("Enter Job ID & Status", "warning")
            return

        self.show_message("Deleting...", "info")

        def task_thread():
            success, msg = delete_from_sheet(label_text, job_id, job_status, user_id)

            def update_ui():
                if success:
                    entry.delete(0, "end")
                    dropdown.set("New")
                    self.update_all_counts()
                    self.show_message("Deleted!", "success")
                    self.update_status(True)
                else:
                    self.show_message(msg, "error")
                    self.update_status(False)

            self.root.after(0, update_ui)

        threading.Thread(target=task_thread, daemon=True).start()

    def setup_section2(self, parent=None):
        p = parent if parent is not None else self.main_frame
        section_frame = ctk.CTkFrame(p, fg_color="#0a121e", corner_radius=10, border_width=1, border_color="#142236")
        section_frame.pack(pady=(0, 12), fill=ctk.X)

        # Table Column Headers
        col_header = ctk.CTkFrame(section_frame, fg_color="transparent")
        col_header.pack(fill=ctk.X, padx=16, pady=(10, 6))

        ctk.CTkLabel(col_header, text="Operation Mode", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=180, anchor="w").pack(side=ctk.LEFT, padx=(0, 10))
        ctk.CTkLabel(col_header, text="Parameter 1", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=120, anchor="w").pack(side=ctk.LEFT, padx=(0, 8))
        ctk.CTkLabel(col_header, text="Parameter 2", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=120, anchor="w").pack(side=ctk.LEFT, padx=(0, 8))
        ctk.CTkLabel(col_header, text="Parameter 3", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=120, anchor="w").pack(side=ctk.LEFT, padx=(0, 12))
        ctk.CTkLabel(col_header, text="Ratio", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=60, anchor="center").pack(side=ctk.LEFT, padx=(0, 15))
        ctk.CTkLabel(col_header, text="Actions", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#64748b", width=105, anchor="center").pack(side=ctk.LEFT)

        # Task Rows
        tasks_config2 = [
            ("Load Transfer", "Load Transfer:", ["Origin ID", "Target ID", "Lane/Bay"]),
            ("Load Audit", "Load Audit:", ["Audit Key", "Inspector", "Checkpoint"]),
            ("Shipping", "Shipping:", ["Manifest #", "Carrier", "Dock Door"]),
            ("Allocation / Backorders", "Allocation/Backorders:", ["SKU Code", "Qty Allocated", "Priority Flag"])
        ]
        for display_name, task_key, placeholders in tasks_config2:
            self.create_textbox_row(section_frame, display_name, task_key, placeholders)

        ctk.CTkFrame(section_frame, fg_color="transparent", height=6).pack()

    def create_textbox_row(self, parent, display_name, task_key, placeholders):
        self.all_task_names.append(task_key)

        row_frame = ctk.CTkFrame(parent, fg_color="transparent", height=38)
        row_frame.pack(fill=ctk.X, padx=16, pady=3)
        row_frame.pack_propagate(False)

        # Operation Mode
        ctk.CTkLabel(
            row_frame, text=display_name, font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#f1f5f9", width=180, anchor="w"
        ).pack(side=ctk.LEFT, padx=(0, 10))

        # 3 Parameter Entries
        entries = []
        for i, ph in enumerate(placeholders):
            e = ctk.CTkEntry(
                row_frame, font=ctk.CTkFont(family="Segoe UI", size=11), width=120, height=32, corner_radius=6,
                border_width=1, fg_color="#060d17", border_color="#182a44", text_color="#ffffff",
                placeholder_text_color="#475569", placeholder_text=ph
            )
            e.pack(side=ctk.LEFT, padx=(0, 8 if i < 2 else 12))
            self.all_entries.append(e)
            entries.append(e)

        # Ratio Badge
        ratio_container = ctk.CTkFrame(row_frame, fg_color="#060d17", border_width=1, border_color="#182a44", corner_radius=6, width=60, height=30)
        ratio_container.pack(side=ctk.LEFT, padx=(0, 15))
        ratio_container.pack_propagate(False)

        count_label = ctk.CTkLabel(
            ratio_container, text="0 - 0", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#ffffff"
        )
        count_label.pack(expand=True)
        self.count_labels.append(count_label)

        # Actions
        actions_frame = ctk.CTkFrame(row_frame, fg_color="transparent", width=105, height=32)
        actions_frame.pack(side=ctk.LEFT)
        actions_frame.pack_propagate(False)

        submit_btn = ctk.CTkButton(
            actions_frame, text="Submit", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), width=60,
            height=30, corner_radius=6, fg_color="#059669", hover_color="#047857", text_color="#ffffff",
            command=lambda: self.submit_action_sheet2(entries, task_key)
        )
        submit_btn.pack(side=ctk.LEFT, padx=(0, 6))
        self.all_buttons.append(submit_btn)

        delete_btn = ctk.CTkButton(
            actions_frame, text="🗑", font=ctk.CTkFont(family="Segoe UI", size=12), width=32,
            height=30, corner_radius=6, fg_color="#101c2e", hover_color="#dc2626", border_width=1, border_color="#182a44",
            text_color="#94a3b8",
            command=lambda: self.delete_action_sheet2(entries, task_key)
        )
        delete_btn.pack(side=ctk.LEFT)
        self.all_buttons.append(delete_btn)

    def submit_action_sheet2(self, entries, label_text):
        if not self.is_edit_mode_enabled:
            self.show_message("Edit mode disabled for past dates", "warning")
            return

        job_id = entries[0].get().strip()
        load_id = entries[1].get().strip()
        lp_count = entries[2].get().strip()
        user_id = self.current_user or (self.username_value.cget("text") if self.username_value and self.username_value.winfo_exists() else "")

        if not job_id:
            self.show_message("Please enter Job ID", "warning")
            return

        if not load_id:
            self.show_message("Please enter Load ID Count", "warning")
            return

        if not lp_count:
            self.show_message("Please enter LP Count", "warning")
            return

        try:
            int(load_id)
        except ValueError:
            self.show_message("Load ID Count must be a number", "warning")
            return

        try:
            int(lp_count)
        except ValueError:
            self.show_message("LP Count must be a number", "warning")
            return

        self.show_message("Saving...", "info")

        def task_thread():
            success, msg, _ = save_to_sheet2(label_text, job_id, load_id, lp_count, user_id)

            def update_ui():
                if success:
                    for entry in entries:
                        entry.delete(0, "end")
                    self.update_all_counts()
                    self.show_message("Saved!", "success")
                    self.update_status(True)
                else:
                    if "Already assigned" in msg:
                        self.show_message(msg, "duplicate")
                    else:
                        self.show_message(msg, "error")
                        self.update_status(False)

            self.root.after(0, update_ui)

        threading.Thread(target=task_thread, daemon=True).start()

    def delete_action_sheet2(self, entries, label_text):
        if not self.is_edit_mode_enabled:
            self.show_message("Edit mode disabled for past dates", "warning")
            return

        job_id = entries[0].get().strip()
        user_id = self.current_user or (self.username_value.cget("text") if self.username_value and self.username_value.winfo_exists() else "")

        if not job_id:
            self.show_message("Enter Job ID", "warning")
            return

        self.show_message("Deleting...", "info")

        def task_thread():
            success, msg = delete_from_sheet2(label_text, job_id, user_id)

            def update_ui():
                if success:
                    entries[0].delete(0, "end")
                    self.update_all_counts()
                    self.show_message("Deleted!", "success")
                    self.update_status(True)
                else:
                    self.show_message(msg, "error")
                    self.update_status(False)

            self.root.after(0, update_ui)

        threading.Thread(target=task_thread, daemon=True).start()

    # ==========================================
    # INTEGRATED LIVE ACTIVITY LOG COMPONENT
    # ==========================================
    def setup_live_activity_log(self, parent=None):
        p = parent if parent is not None else self.main_frame
        log_card = ctk.CTkFrame(p, fg_color="#0a121e", corner_radius=10, border_width=1, border_color="#142236")
        log_card.pack(pady=(0, 10), fill=ctk.BOTH, expand=True)

        # Top Control / Header Bar of Activity Log
        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.pack(fill=ctk.X, padx=16, pady=(10, 8))

        # Left Info & Status
        hdr_left = ctk.CTkFrame(log_header, fg_color="transparent")
        hdr_left.pack(side=ctk.LEFT)

        ctk.CTkLabel(
            hdr_left, text="●", font=ctk.CTkFont(size=11), text_color="#00e5ff"
        ).pack(side=ctk.LEFT, padx=(0, 8))

        ctk.CTkLabel(
            hdr_left, text="LIVE ACTIVITY & CONNECTION LOG",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#e2e8f0"
        ).pack(side=ctk.LEFT, padx=(0, 12))

        # Inline status pill
        status_color = "#10b981" if self.connection_status else "#ef4444"
        status_txt = "● Online (Synced)" if self.connection_status else "● Offline (Cached)"
        self.inline_status_badge = ctk.CTkLabel(
            hdr_left, text=status_txt,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=status_color
        )
        self.inline_status_badge.pack(side=ctk.LEFT, padx=(0, 10))

        # Inline latency
        lat_text = f"⚡ {self.last_latency_ms} ms" if getattr(self, 'last_latency_ms', None) else "⚡ -- ms"
        self.inline_latency_label = ctk.CTkLabel(
            hdr_left, text=lat_text,
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color="#64748b"
        )
        self.inline_latency_label.pack(side=ctk.LEFT, padx=(0, 10))

        # Right Action Buttons
        hdr_right = ctk.CTkFrame(log_header, fg_color="transparent")
        hdr_right.pack(side=ctk.RIGHT)

        # Test Connection button
        self.inline_test_btn = ctk.CTkButton(
            hdr_right, text="🔄 Test Connection",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            width=120, height=28, corner_radius=6,
            fg_color="#059669", hover_color="#047857", text_color="#ffffff",
            command=self._run_live_connection_test
        )
        self.inline_test_btn.pack(side=ctk.LEFT, padx=(0, 6))

        # Copy button
        copy_btn = ctk.CTkButton(
            hdr_right, text="📋 Copy",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            width=65, height=28, corner_radius=6,
            fg_color="#101c2e", hover_color="#182a44", border_width=1, border_color="#182a44", text_color="#94a3b8",
            command=self._copy_activity_log
        )
        copy_btn.pack(side=ctk.LEFT, padx=(0, 6))

        # Clear button
        clear_btn = ctk.CTkButton(
            hdr_right, text="🗑 Clear",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            width=58, height=28, corner_radius=6,
            fg_color="#101c2e", hover_color="#dc2626", border_width=1, border_color="#182a44", text_color="#94a3b8",
            command=self._clear_activity_log
        )
        clear_btn.pack(side=ctk.LEFT, padx=(0, 8))

        # Filter dropdown
        self.inline_filter_menu = ctk.CTkOptionMenu(
            hdr_right, values=["All Events", "Connection", "Data Sync", "Tasks", "Cache"],
            font=ctk.CTkFont(family="Segoe UI", size=10), width=105, height=28,
            corner_radius=6, fg_color="#060d17", button_color="#0d1b2a",
            button_hover_color="#162e4c", text_color="#ffffff",
            dropdown_fg_color="#0c182b", dropdown_text_color="#ffffff",
            dropdown_hover_color="#162e4c",
            command=lambda v: self._refresh_inline_activity_log()
        )
        self.inline_filter_menu.pack(side=ctk.LEFT)
        self.inline_filter_menu.set(getattr(self, 'log_filter_category', 'All Events'))

        # Log Scrollable Frame (Integrated Live Terminal)
        self.inline_log_scroll_frame = ctk.CTkScrollableFrame(
            log_card, fg_color="#040810", border_width=1, border_color="#132034",
            corner_radius=8, height=140, scrollbar_button_color="#142236", scrollbar_button_hover_color="#1a2d47"
        )
        self.inline_log_scroll_frame.pack(fill=ctk.BOTH, expand=True, padx=16, pady=(0, 12))

        self._refresh_inline_activity_log()

    def _refresh_inline_activity_log(self):
        if not hasattr(self, 'inline_log_scroll_frame') or not self.inline_log_scroll_frame or not self.inline_log_scroll_frame.winfo_exists():
            return
        for w in self.inline_log_scroll_frame.winfo_children():
            w.destroy()

        cat_filter = self.inline_filter_menu.get() if hasattr(self, 'inline_filter_menu') and self.inline_filter_menu.winfo_exists() else "All Events"
        with _activity_log_lock:
            logs_copy = list(_activity_logs)

        filtered = []
        for l in logs_copy:
            cat = l.get("category", "").upper()
            if cat_filter == "All Events":
                filtered.append(l)
            elif cat_filter == "Connection" and cat == "CONNECTION":
                filtered.append(l)
            elif cat_filter == "Data Sync" and cat == "SYNC":
                filtered.append(l)
            elif cat_filter == "Tasks" and cat == "TASK":
                filtered.append(l)
            elif cat_filter == "Cache" and cat == "CACHE":
                filtered.append(l)

        if not filtered:
            ctk.CTkLabel(
                self.inline_log_scroll_frame,
                text="No log events recorded yet.",
                font=ctk.CTkFont(family="Consolas", size=10),
                text_color="#475569"
            ).pack(pady=15)
            return

        badge_colors = {
            "SUCCESS": ("#064e3b", "#34d399"),
            "ERROR": ("#7f1d1d", "#f87171"),
            "WARN": ("#78350f", "#fbbf24"),
            "INFO": ("#1e293b", "#94a3b8")
        }

        # Cap rendered log items to the most recent 25 to prevent GUI freeze/widget churn
        display_items = filtered[-25:]

        for item in reversed(display_items):
            row = ctk.CTkFrame(self.inline_log_scroll_frame, fg_color="transparent")
            row.pack(fill=ctk.X, pady=2, padx=4)

            # Timestamp
            ctk.CTkLabel(
                row, text=item["timestamp"],
                font=ctk.CTkFont(family="Consolas", size=10),
                text_color="#64748b", width=65, anchor="w"
            ).pack(side=ctk.LEFT)

            # Badge
            lvl = item.get("level", "INFO")
            bg_c, fg_c = badge_colors.get(lvl, ("#1e293b", "#94a3b8"))
            cat_text = item.get("category", "INFO")[:7]

            badge = ctk.CTkFrame(row, fg_color=bg_c, corner_radius=4, height=18)
            badge.pack(side=ctk.LEFT, padx=(4, 8))
            badge.pack_propagate(False)

            ctk.CTkLabel(
                badge, text=f"[{cat_text}]",
                font=ctk.CTkFont(family="Consolas", size=8, weight="bold"),
                text_color=fg_c
            ).pack(padx=4, pady=0)

            # Message
            msg_label = ctk.CTkLabel(
                row, text=item["message"],
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color="#e2e8f0", anchor="w"
            )
            msg_label.pack(side=ctk.LEFT, fill=ctk.X, expand=True)

    def _on_activity_log_added(self, entry):
        if getattr(self, '_log_refresh_timer', None) is not None:
            return
        def _do_refresh():
            self._log_refresh_timer = None
            self._refresh_inline_activity_log()
            if hasattr(self, 'activity_log_window') and self.activity_log_window is not None and self.activity_log_window.winfo_exists():
                self._refresh_activity_log_view()
        self._log_refresh_timer = self.root.after(200, _do_refresh)

    def _copy_activity_log(self):
        with _activity_log_lock:
            lines = [f"[{l['timestamp']}] [{l['category']}] [{l['level']}] {l['message']}" for l in _activity_logs]
        text_data = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(text_data)
        self.show_message("Activity log copied to clipboard!", "success")

    def _clear_activity_log(self):
        with _activity_log_lock:
            _activity_logs.clear()
        add_activity_log("SYSTEM", "Activity log cleared", "INFO")
        self._refresh_inline_activity_log()
        if hasattr(self, 'activity_log_window') and self.activity_log_window is not None and self.activity_log_window.winfo_exists():
            self._refresh_activity_log_view()

    def _run_live_connection_test(self):
        if hasattr(self, 'inline_test_btn') and self.inline_test_btn and self.inline_test_btn.winfo_exists():
            self.inline_test_btn.configure(text="Testing...", state="disabled")
        if hasattr(self, 'test_conn_btn') and self.test_conn_btn and self.test_conn_btn.winfo_exists():
            self.test_conn_btn.configure(text="Testing...", state="disabled")

        def test_worker():
            res = test_connection_diagnostics()
            def update_ui():
                if hasattr(self, 'inline_test_btn') and self.inline_test_btn and self.inline_test_btn.winfo_exists():
                    self.inline_test_btn.configure(text="🔄 Test Connection", state="normal")
                if hasattr(self, 'test_conn_btn') and self.test_conn_btn and self.test_conn_btn.winfo_exists():
                    self.test_conn_btn.configure(text="🔄 Test Connection Now", state="normal")

                self.last_latency_ms = res["latency_ms"]
                self.connection_status = res["connected"]
                self.update_status(res["connected"])

                if hasattr(self, 'inline_latency_label') and self.inline_latency_label and self.inline_latency_label.winfo_exists():
                    self.inline_latency_label.configure(text=f"⚡ {res['latency_ms']} ms")
                if hasattr(self, 'inline_status_badge') and self.inline_status_badge and self.inline_status_badge.winfo_exists():
                    self.inline_status_badge.configure(
                        text="● Online (Synced)" if res["connected"] else "● Offline (Cached)",
                        text_color="#10b981" if res["connected"] else "#ef4444"
                    )

                self._refresh_inline_activity_log()
                if hasattr(self, 'activity_log_window') and self.activity_log_window is not None and self.activity_log_window.winfo_exists():
                    self._refresh_activity_log_view()

            self.root.after(0, update_ui)

        threading.Thread(target=test_worker, daemon=True).start()

    def setup_footer(self, parent=None):
        p = parent if parent is not None else self.main_frame
        footer_frame = ctk.CTkFrame(p, fg_color="transparent")
        footer_frame.pack(fill=ctk.X, pady=(6, 10))

        # RIGHT: Refresh Records Button
        refresh_btn = ctk.CTkButton(
            footer_frame,
            text="🔄 Refresh Records",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            width=135,
            height=32,
            corner_radius=8,
            fg_color="#0a121e",
            hover_color="#142236",
            border_width=1,
            border_color="#182a44",
            text_color="#ffffff",
            command=lambda: [self.update_all_counts(), self.show_message("Records refreshed!", "success")]
        )
        refresh_btn.pack(side=ctk.RIGHT)

        # Call update_edit_mode after UI is fully built
        self.root.after(100, self.update_edit_mode)
        self.root.after(300, self.update_edit_mode)


# ==========================================
# RUN THE APPLICATION
# ==========================================
if __name__ == "__main__":
    root = ctk.CTk()
    app = EFLApp(root)
    root.mainloop()
