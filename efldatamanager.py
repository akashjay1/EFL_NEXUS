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
            return sheet, "Success"
        except Exception as e:
            _connection_status = False
            return None, str(e)

def fetch_all_sheets_batch():
    """Fetch Sheet1, Sheet2, Sheet3 in a SINGLE batch API request (~0.7s)."""
    global _records_cache, _records2_cache, _records3_cache, _cache_timestamps, _connection_status
    with _sheets_lock:
        try:
            sheet, msg = connect_to_sheets()
            if not sheet:
                _connection_status = False
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

            return True, "Success"
        except Exception as e:
            _connection_status = False
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
        if sheet_name == SHEET3_NAME:
            if _records3_cache is not None and cache_key in _cache_timestamps:
                if current_time - _cache_timestamps[cache_key] < 60:
                    return _records3_cache
        elif sheet_name == SHEET2_NAME:
            if _records2_cache is not None and cache_key in _cache_timestamps:
                if current_time - _cache_timestamps[cache_key] < 60:
                    return _records2_cache
        else:
            if _records_cache is not None and cache_key in _cache_timestamps:
                if current_time - _cache_timestamps[cache_key] < 60:
                    return _records_cache

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
            return False, msg, None
        is_duplicate, existing_user = check_duplicate(task, job_id, job_status)
        if is_duplicate:
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
        return True, "Saved successfully!", None
    except Exception as e:
        print(f"Error saving: {e}")
        return False, str(e), None

def save_to_sheet2(task, job_id, load_id, lp_count, user_id):
    try:
        sheet, msg = connect_to_sheets(force_refresh=False, sheet_name=SHEET2_NAME)
        if not sheet:
            return False, msg, None
        is_duplicate, existing_user = check_duplicate_sheet2(task, job_id, load_id, lp_count)
        if is_duplicate:
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
        return True, "Saved successfully!", None
    except Exception as e:
        print(f"Error saving to Sheet2: {e}")
        return False, str(e), None

def delete_from_sheet(task, job_id, job_status, user_id):
    try:
        sheet, msg = connect_to_sheets()
        if not sheet:
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
        return True, "Deleted successfully"
    except Exception as e:
        print(f"Error deleting: {e}")
        return False, str(e)

def delete_from_sheet2(task, job_id, user_id):
    try:
        sheet, msg = connect_to_sheets(force_refresh=False, sheet_name=SHEET2_NAME)
        if not sheet:
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
        return True, "Deleted successfully"
    except Exception as e:
        print(f"Error deleting from Sheet2: {e}")
        return False, str(e)


# ==========================================
# SET APPEARANCE
# ==========================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


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
        self.connection_status = False
        self.is_loading = False
        # Ensure local disk cache is in memory for 0s startup
        _load_local_disk_cache()

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

        self.login_frame = ctk.CTkFrame(self.container, fg_color="#12121e")
        self.login_frame.pack(fill=ctk.BOTH, expand=True)

        # Center Card Container
        center_container = ctk.CTkFrame(self.login_frame, fg_color="transparent")
        center_container.place(relx=0.5, rely=0.5, anchor="center")

        # Header Brand Banner
        header_card = ctk.CTkFrame(center_container, fg_color="#FF6B00", height=65, corner_radius=10, width=440)
        header_card.pack(fill=ctk.X, pady=(0, 15))
        header_card.pack_propagate(False)

        ctk.CTkLabel(
            header_card,
            text="USER DATA MANAGER",
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color="white"
        ).pack(expand=True)

        # Card Frame with border
        card = ctk.CTkFrame(
            center_container,
            fg_color=("#ffffff", "#1a1a2e"),
            corner_radius=12,
            border_width=1,
            border_color=("#d0d0d0", "#2d2d44"),
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
            segmented_button_selected_color="#FF6B00",
            segmented_button_selected_hover_color="#e05d00",
            segmented_button_unselected_color=("#e8e0d8", "#2b2b44"),
            segmented_button_unselected_hover_color=("#d5cdc5", "#3d3d54")
        )
        self.auth_tabview.pack(padx=15, pady=(10, 10), fill=ctk.BOTH, expand=True)

        tab_login = self.auth_tabview.add("Sign In")
        tab_register = self.auth_tabview.add("Register User")

        # --- SIGN IN TAB ---
        ctk.CTkLabel(
            tab_login,
            text="User ID",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#333333", "#e0e0e0")
        ).pack(anchor="w", padx=15, pady=(10, 3))

        registered_users = get_registered_users()
        default_user_val = registered_users[0] if registered_users else ""

        self.login_user_combo = ctk.CTkComboBox(
            tab_login,
            values=registered_users if registered_users else [""],
            height=34,
            corner_radius=6,
            fg_color=("#f5f5f5", "#2b2b44"),
            border_color=("#cccccc", "#3d3d54"),
            text_color=("#1a1a2e", "#e0e0e0"),
            dropdown_fg_color=("#ffffff", "#2b2b44"),
            dropdown_text_color=("#1a1a2e", "#e0e0e0")
        )
        self.login_user_combo.set(default_user_val)
        self.login_user_combo.pack(fill=ctk.X, padx=15, pady=(0, 10))

        ctk.CTkLabel(
            tab_login,
            text="Password",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#333333", "#e0e0e0")
        ).pack(anchor="w", padx=15, pady=(0, 3))

        pwd_row = ctk.CTkFrame(tab_login, fg_color="transparent")
        pwd_row.pack(fill=ctk.X, padx=15, pady=(0, 8))

        self.login_pass_entry = ctk.CTkEntry(
            pwd_row,
            show="•",
            height=34,
            corner_radius=6,
            fg_color=("#f5f5f5", "#2b2b44"),
            border_color=("#cccccc", "#3d3d54"),
            text_color=("#1a1a2e", "#e0e0e0"),
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
            fg_color=("#e8e0d8", "#2b2b44"),
            hover_color=("#d5cdc5", "#3d3d54"),
            text_color=("#333333", "#e0e0e0"),
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
            fg_color="#FF6B00",
            hover_color="#e05d00"
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
            fg_color="#FF6B00",
            hover_color="#e05d00",
            text_color="white",
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
            text_color=("#333333", "#e0e0e0")
        ).pack(anchor="w", padx=15, pady=(5, 2))

        self.reg_user_entry = ctk.CTkEntry(
            tab_register,
            height=32,
            corner_radius=6,
            fg_color=("#f5f5f5", "#2b2b44"),
            border_color=("#cccccc", "#3d3d54"),
            text_color=("#1a1a2e", "#e0e0e0"),
            placeholder_text="e.g. Akash, Chamara, John"
        )
        self.reg_user_entry.pack(fill=ctk.X, padx=15, pady=(0, 6))

        ctk.CTkLabel(
            tab_register,
            text="New Password",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#333333", "#e0e0e0")
        ).pack(anchor="w", padx=15, pady=(0, 2))

        self.reg_pass_entry = ctk.CTkEntry(
            tab_register,
            show="•",
            height=32,
            corner_radius=6,
            fg_color=("#f5f5f5", "#2b2b44"),
            border_color=("#cccccc", "#3d3d54"),
            text_color=("#1a1a2e", "#e0e0e0"),
            placeholder_text="Enter password"
        )
        self.reg_pass_entry.pack(fill=ctk.X, padx=15, pady=(0, 6))

        ctk.CTkLabel(
            tab_register,
            text="Confirm Password",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#333333", "#e0e0e0")
        ).pack(anchor="w", padx=15, pady=(0, 2))

        self.reg_confirm_entry = ctk.CTkEntry(
            tab_register,
            show="•",
            height=32,
            corner_radius=6,
            fg_color=("#f5f5f5", "#2b2b44"),
            border_color=("#cccccc", "#3d3d54"),
            text_color=("#1a1a2e", "#e0e0e0"),
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
        self.main_frame = ctk.CTkFrame(self.container, fg_color="#12121e")
        self.main_frame.pack(fill=ctk.BOTH, expand=True)

        # Scrollable container so it fits on any screen height/width
        self.content_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        self.content_frame.pack(fill=ctk.BOTH, expand=True, padx=25, pady=15)

        # Reset collections
        self.count_labels = []
        self.all_task_names = []
        self.all_entries = []
        self.all_dropdowns = []
        self.all_buttons = []
        self.selected_date = datetime.now().date()
        self.is_edit_mode_enabled = True
        self.is_first_load = True

        # Build UI Components
        self.setup_header(self.content_frame)
        self.setup_top_user_date_row(self.content_frame)
        self.setup_section1(self.content_frame)
        self.setup_section2(self.content_frame)
        self.setup_footer(self.content_frame)

        # Reset inputs
        self.root.after(20, self.reset_all_inputs)

        # If cache is available, display counts immediately!
        if _records_cache:
            self.update_status(True)
            self.update_all_counts()

        # Load fresh data in background via fast single-batch API call
        self.root.after(50, self.load_data_background)

        # Start status check
        self.root.after(5000, self.check_connection_status)

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
        if self.status_dot and self.status_dot.winfo_exists():
            color = "#4CAF50" if is_connected else "#f44336"
            self.status_dot.configure(fg_color=color)
        if self.status_label and self.status_label.winfo_exists():
            status_text = "Online" if is_connected else "Offline"
            self.status_label.configure(text=status_text)

    def check_connection_status(self):
        def check():
            try:
                sheet, msg = connect_to_sheets()
                status = sheet is not None
            except Exception:
                status = False
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
        """Reset all dropdowns to '- Any -' and clear all entry boxes"""
        for entry in self.all_entries:
            try:
                if entry.winfo_exists():
                    entry.delete(0, "end")
            except Exception as e:
                print(f"Error clearing entry: {e}")

        for dropdown in self.all_dropdowns:
            try:
                if dropdown.winfo_exists():
                    dropdown.set("- Any -")
            except Exception as e:
                print(f"Error resetting dropdown: {e}")

        self.root.update_idletasks()

    # ==========================================================
    # UI SETUP METHODS
    # ==========================================================
    def setup_header(self, parent=None):
        p = parent if parent is not None else self.main_frame
        header_frame = ctk.CTkFrame(p, fg_color="#FF6B00", height=55, corner_radius=10)
        header_frame.pack(fill=ctk.X, pady=(0, 15))
        header_frame.pack_propagate(False)

        ctk.CTkLabel(
            header_frame,
            text="USER DATA MANAGER",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="white"
        ).pack(expand=True)

    def setup_top_user_date_row(self, parent=None):
        p = parent if parent is not None else self.main_frame
        top_row = ctk.CTkFrame(p, fg_color="transparent")
        top_row.pack(fill=ctk.X, pady=(0, 10))

        top_row.grid_columnconfigure(0, weight=1)
        top_row.grid_columnconfigure(1, weight=2)
        top_row.grid_columnconfigure(2, weight=1)

        # LEFT: User ID & Logout Button
        user_frame = ctk.CTkFrame(top_row, fg_color="transparent")
        user_frame.grid(row=0, column=0, sticky="w", padx=(0, 10))

        ctk.CTkLabel(
            user_frame,
            text="User ID:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#333333", "#e0e0e0")
        ).pack(side=ctk.LEFT, padx=(0, 6))

        user_badge = ctk.CTkFrame(user_frame, fg_color=("#e8e0d8", "#2b2b44"), corner_radius=6)
        user_badge.pack(side=ctk.LEFT, padx=(0, 8))

        self.username_value = ctk.CTkLabel(
            user_badge,
            text=self.current_user or "User",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#1a237e", "#64b5f6"),
            padx=8,
            pady=3
        )
        self.username_value.pack(side=ctk.LEFT)

        logout_btn = ctk.CTkButton(
            user_frame,
            text="Logout",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=55,
            height=26,
            corner_radius=6,
            fg_color=("#d0d0d0", "#2d2d44"),
            hover_color=("#f44336", "#d32f2f"),
            text_color=("#333333", "#e0e0e0"),
            command=self.logout
        )
        logout_btn.pack(side=ctk.LEFT)

        # CENTER: Message Label
        self.message_label = ctk.CTkLabel(
            top_row,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#4CAF50",
            anchor="center"
        )
        self.message_label.grid(row=0, column=1, sticky="ew", padx=10)

        # RIGHT: Date Selector
        date_frame = ctk.CTkFrame(top_row, fg_color="transparent")
        date_frame.grid(row=0, column=2, sticky="e")

        ctk.CTkLabel(
            date_frame,
            text="Date:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#333333", "#e0e0e0")
        ).pack(side=ctk.LEFT, padx=(0, 10))

        self.date_label = ctk.CTkLabel(
            date_frame,
            text=self.selected_date.strftime("%d-%m-%Y"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#1a237e", "#64b5f6"),
            cursor="hand2"
        )
        self.date_label.pack(side=ctk.LEFT, padx=(0, 5))
        self.date_label.bind("<Button-1>", lambda e: self.toggle_dropdown_popup())

        self.date_arrow = ctk.CTkLabel(
            date_frame,
            text="▼",
            font=ctk.CTkFont(size=11),
            text_color=("#666666", "#888888"),
            cursor="hand2"
        )
        self.date_arrow.pack(side=ctk.LEFT)
        self.date_arrow.bind("<Button-1>", lambda e: self.toggle_dropdown_popup())

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
                self.root.update_idletasks()
                self.root.focus_force()
            except ValueError:
                pass

        def build_calendar(year, month):
            for widget in popup_frame.winfo_children():
                widget.destroy()

            nav_container = ctk.CTkFrame(popup_frame, fg_color="#2d2d44", corner_radius=6, height=34)
            nav_container.pack(fill=ctk.X, pady=(10, 8), padx=6)
            nav_container.pack_propagate(False)

            prev_btn = ctk.CTkButton(
                nav_container, text="◀", width=30, height=26, fg_color="#3d3d54",
                text_color="#e0e0e0", hover_color="#4d4d64", corner_radius=4, font=ctk.CTkFont(size=12),
                command=lambda: navigate_month(-1)
            )
            prev_btn.pack(side=ctk.LEFT, padx=(6, 4))

            month_year_label = ctk.CTkLabel(
                nav_container, text=f"{calendar.month_name[month]} {year}",
                font=ctk.CTkFont(size=13, weight="bold"), text_color="#e0e0e0"
            )
            month_year_label.pack(side=ctk.LEFT, expand=True)

            next_btn = ctk.CTkButton(
                nav_container, text="▶", width=30, height=26, fg_color="#3d3d54",
                text_color="#e0e0e0", hover_color="#4d4d64", corner_radius=4, font=ctk.CTkFont(size=12),
                command=lambda: navigate_month(1)
            )
            next_btn.pack(side=ctk.RIGHT, padx=(4, 6))

            day_frame = ctk.CTkFrame(popup_frame, fg_color="transparent")
            day_frame.pack(fill=ctk.X, pady=(0, 3))
            day_names = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
            for day in day_names:
                ctk.CTkLabel(
                    day_frame, text=day, font=ctk.CTkFont(size=9, weight="bold"),
                    text_color=("#666666", "#888888"), width=30, anchor="center"
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
                            fg_color="#4CAF50" if is_selected else ("#FF6B00" if is_today else ("#e8e0d8" if not is_future else "#f0f0f0")),
                            text_color="white" if (is_selected or is_today) else ("#333333" if not is_future else "#999999"),
                            hover_color="#45a049" if not is_future else "#f0f0f0",
                            state="disabled" if is_future else "normal",
                            command=lambda d=day: select_date(year, month, d)
                        )
                        btn.pack(side=ctk.LEFT, padx=1)

            bottom_frame = ctk.CTkFrame(popup_frame, fg_color="transparent")
            bottom_frame.pack(fill=ctk.X, pady=(10, 10))
            today_btn = ctk.CTkButton(
                bottom_frame, text="Today", font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#4CAF50", hover_color="#45a049", height=26, width=65,
                command=lambda: select_date(today.year, today.month, today.day)
            )
            today_btn.pack(side=ctk.LEFT, padx=(6, 0))
            close_btn = ctk.CTkButton(
                bottom_frame, text="Close", font=ctk.CTkFont(size=10), fg_color="#f44336",
                hover_color="#d32f2f", height=26, width=65, command=self.close_popup_safely
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

        popup_frame = ctk.CTkFrame(self.popup, fg_color=("#ffffff", "#1a1a2e"), corner_radius=6)
        popup_frame.pack(fill=ctk.BOTH, expand=True)
        build_calendar(current_year, current_month)
        self.date_label.configure(text_color="#4CAF50")

        def on_global_click(event):
            if self.popup is not None and self.popup.winfo_exists():
                try:
                    px = self.popup.winfo_rootx()
                    py = self.popup.winfo_rooty()
                    pw = self.popup.winfo_width()
                    ph = self.popup.winfo_height()
                    if not (px <= event.x_root <= px + pw and py <= event.y_root <= py + ph):
                        dlx = self.date_label.winfo_rootx()
                        dly = self.date_label.winfo_rooty()
                        dlw = self.date_label.winfo_width() + 30
                        dlh = self.date_label.winfo_height()
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
            if hasattr(self, 'date_label') and self.date_label.winfo_exists():
                self.date_label.configure(text_color=("#1a237e", "#64b5f6"))

    def position_popup(self, event=None):
        if self.popup is not None and self.popup.winfo_exists():
            try:
                x = self.date_label.winfo_rootx() - 70
                y = self.date_label.winfo_rooty() + 30
                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()
                popup_width = 240
                popup_height = 310

                if x + popup_width > screen_width:
                    x = screen_width - popup_width - 10
                if x < 10:
                    x = 10
                if y + popup_height > screen_height:
                    y = self.date_label.winfo_rooty() - popup_height - 10
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
        self.root.update_idletasks()

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
                    counts.append(f"{val[0]}-{val[1]}")
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
        section_frame = ctk.CTkFrame(p, fg_color=("#ffffff", "#1a1a2e"), corner_radius=8, border_width=1, border_color=("#d0d0d0", "#2d2d44"))
        section_frame.pack(pady=10, fill=ctk.X)

        input_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        input_frame.pack(pady=10, padx=10, fill=ctk.X)

        tasks = ["GDN Reconciliation:", "GRN Reconciliation:", "GDN Creation:", "GRN Creation:", "Load Plan or Asn:"]
        for task in tasks:
            self.create_dropdown_row(input_frame, task)

    def create_dropdown_row(self, parent, label_text):
        self.all_task_names.append(label_text)

        row_frame = ctk.CTkFrame(parent, fg_color="transparent", height=35)
        row_frame.pack(pady=3, fill=ctk.X)
        row_frame.pack_propagate(False)

        ctk.CTkLabel(
            row_frame, text=label_text, font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#333333", "#e0e0e0"), width=160, anchor="w"
        ).pack(side=ctk.LEFT, padx=(0, 10))

        entry = ctk.CTkEntry(
            row_frame, font=ctk.CTkFont(size=11), width=180, height=32, corner_radius=6,
            border_width=1, fg_color=("#ffffff", "#2b2b44"), text_color=("#1a1a2e", "#e0e0e0"),
            placeholder_text="Enter Job ID"
        )
        entry.pack(side=ctk.LEFT, padx=(0, 10))
        self.all_entries.append(entry)

        options = ["- Any -", "New", "Revise", "Separate"]
        if label_text in ["GDN Reconciliation:", "GRN Reconciliation:", "Load Plan or Asn:"]:
            options = ["- Any -", "New", "Revise"]

        dropdown = ctk.CTkOptionMenu(
            row_frame, values=options, font=ctk.CTkFont(size=11), width=140, height=32,
            corner_radius=6, fg_color=("#ffffff", "#2b2b44"), button_color=("#e8e0d8", "#3d3d54"),
            button_hover_color=("#d5cdc5", "#4d4d64"), text_color=("#1a1a2e", "#e0e0e0"))
        dropdown.pack(side=ctk.LEFT, padx=(0, 15))
        dropdown.set("- Any -")
        self.all_dropdowns.append(dropdown)

        submit_btn = ctk.CTkButton(
            row_frame, text="Submit", font=ctk.CTkFont(size=11, weight="bold"), width=65,
            height=32, corner_radius=6, fg_color="#4CAF50", hover_color="#45a049",
            command=lambda: self.submit_action_sheet1(entry, dropdown, label_text)
        )
        submit_btn.pack(side=ctk.LEFT, padx=(5, 5))
        self.all_buttons.append(submit_btn)

        delete_btn = ctk.CTkButton(
            row_frame, text="Delete", font=ctk.CTkFont(size=11, weight="bold"), width=65,
            height=32, corner_radius=6, fg_color="#f44336", hover_color="#d32f2f",
            command=lambda: self.delete_action_sheet1(entry, dropdown, label_text)
        )
        delete_btn.pack(side=ctk.LEFT, padx=(0, 5))
        self.all_buttons.append(delete_btn)

        count_label = ctk.CTkLabel(
            row_frame, text="0", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#333333", "#e0e0e0"), width=60, anchor="w"
        )
        count_label.pack(side=ctk.LEFT, padx=(15, 0))
        self.count_labels.append(count_label)

    def submit_action_sheet1(self, entry, dropdown, label_text):
        if not self.is_edit_mode_enabled:
            self.show_message("Edit mode disabled for past dates", "warning")
            return

        job_id = entry.get().strip()
        job_status = dropdown.get()
        user_id = self.current_user or (self.username_value.cget("text") if self.username_value and self.username_value.winfo_exists() else "")

        if not job_id or job_status == "- Any -":
            self.show_message("Enter Job ID & Status", "warning")
            return

        self.show_message("Saving...", "info")

        def task_thread():
            success, msg, _ = save_to_sheet(label_text, job_id, job_status, user_id)

            def update_ui():
                if success:
                    entry.delete(0, "end")
                    dropdown.set("- Any -")
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

        if not job_id or job_status == "- Any -":
            self.show_message("Enter Job ID & Status", "warning")
            return

        self.show_message("Deleting...", "info")

        def task_thread():
            success, msg = delete_from_sheet(label_text, job_id, job_status, user_id)

            def update_ui():
                if success:
                    entry.delete(0, "end")
                    dropdown.set("- Any -")
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
        section_frame = ctk.CTkFrame(p, fg_color=("#ffffff", "#1a1a2e"), corner_radius=8, border_width=1, border_color=("#d0d0d0", "#2d2d44"))
        section_frame.pack(pady=10, fill=ctk.X)

        input_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        input_frame.pack(pady=10, padx=10, fill=ctk.X)

        tasks = ["Load Transfer:", "Load Audit:", "Shipping:", "Allocation/Backorders:"]
        for task in tasks:
            self.create_textbox_row(input_frame, task)

    def create_textbox_row(self, parent, label_text):
        self.all_task_names.append(label_text)

        row_frame = ctk.CTkFrame(parent, fg_color="transparent", height=35)
        row_frame.pack(pady=3, fill=ctk.X)
        row_frame.pack_propagate(False)

        ctk.CTkLabel(
            row_frame, text=label_text, font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#333333", "#e0e0e0"), width=190, anchor="w"
        ).pack(side=ctk.LEFT, padx=(0, 10))

        entry1 = ctk.CTkEntry(
            row_frame, font=ctk.CTkFont(size=11), width=100, height=32, corner_radius=6,
            border_width=1, fg_color=("#ffffff", "#2b2b44"), text_color=("#1a1a2e", "#e0e0e0"),
            placeholder_text="Job ID"
        )
        entry1.pack(side=ctk.LEFT, padx=(0, 10))
        self.all_entries.append(entry1)

        entry2 = ctk.CTkEntry(
            row_frame, font=ctk.CTkFont(size=11), width=90, height=32, corner_radius=6,
            border_width=1, fg_color=("#ffffff", "#2b2b44"), text_color=("#1a1a2e", "#e0e0e0"),
            placeholder_text="Load ID Count"
        )
        entry2.pack(side=ctk.LEFT, padx=(0, 10))
        self.all_entries.append(entry2)

        entry3 = ctk.CTkEntry(
            row_frame, font=ctk.CTkFont(size=11), width=90, height=32, corner_radius=6,
            border_width=1, fg_color=("#ffffff", "#2b2b44"), text_color=("#1a1a2e", "#e0e0e0"),
            placeholder_text="LP Count"
        )
        entry3.pack(side=ctk.LEFT, padx=(0, 10))
        self.all_entries.append(entry3)

        submit_btn = ctk.CTkButton(
            row_frame, text="Submit", font=ctk.CTkFont(size=11, weight="bold"), width=65,
            height=32, corner_radius=6, fg_color="#4CAF50", hover_color="#45a049",
            command=lambda: self.submit_action_sheet2([entry1, entry2, entry3], label_text)
        )
        submit_btn.pack(side=ctk.LEFT, padx=(5, 5))
        self.all_buttons.append(submit_btn)

        delete_btn = ctk.CTkButton(
            row_frame, text="Delete", font=ctk.CTkFont(size=11, weight="bold"), width=65,
            height=32, corner_radius=6, fg_color="#f44336", hover_color="#d32f2f",
            command=lambda: self.delete_action_sheet2([entry1, entry2, entry3], label_text)
        )
        delete_btn.pack(side=ctk.LEFT, padx=(0, 5))
        self.all_buttons.append(delete_btn)

        count_label = ctk.CTkLabel(
            row_frame, text="0-0", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#333333", "#e0e0e0"), width=60, anchor="w"
        )
        count_label.pack(side=ctk.LEFT, padx=(15, 0))
        self.count_labels.append(count_label)

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

    def setup_footer(self, parent=None):
        p = parent if parent is not None else self.main_frame
        footer_frame = ctk.CTkFrame(p, fg_color="transparent")
        footer_frame.pack(pady=15, fill=ctk.X)

        footer_container = ctk.CTkFrame(footer_frame, fg_color="transparent")
        footer_container.pack(fill=ctk.X)

        footer_container.grid_columnconfigure(0, weight=1)
        footer_container.grid_columnconfigure(1, weight=1)

        # LEFT: Status Indicator
        status_frame = ctk.CTkFrame(footer_container, fg_color="transparent")
        status_frame.grid(row=0, column=0, sticky="w")

        self.status_dot = ctk.CTkFrame(
            status_frame,
            width=12,
            height=12,
            corner_radius=6,
            fg_color="#f44336"
        )
        self.status_dot.pack(side=ctk.LEFT, padx=(0, 8))
        self.status_dot.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="Offline",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#333333", "#e0e0e0")
        )
        self.status_label.pack(side=ctk.LEFT)

        # RIGHT: Refresh Button
        refresh_btn = ctk.CTkButton(
            footer_container,
            text="Refresh",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=80,
            height=28,
            corner_radius=6,
            fg_color=("#4267CE", "#1565c0"),
            hover_color=("#365899", "#0d47a1"),
            command=lambda: [self.update_all_counts(), self.show_message("Refreshed!", "success")]
        )
        refresh_btn.grid(row=0, column=1, sticky="e")

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
