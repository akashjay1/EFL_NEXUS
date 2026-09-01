"""
Körber login bot — opens a brand new browser window every time you run it,
navigates to the login page, and logs in automatically.

SETUP (one-time):
1. pip install selenium python-dotenv webdriver-manager
2. Create a file named ".env" in the same folder as this script, containing:

    KORBER_URL=https://lopwaprodweb.koerbercloud.com/core/Default.html
    KORBER_USER=LPAKASHM
    KORBER_PASS=your_actual_password_here

   (Do NOT put your password directly in this .py file — keep it in .env,
   and don't share .env or paste your password into chat again.)

RUN:
    python korber_login_bot.py
"""

import os
import sys
import time
import logging
import json
from pathlib import Path
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Look for .env next to the executable if frozen, or next to this script in dev mode.
if getattr(sys, "frozen", False):
    _base = Path(sys.executable).resolve().parent
    ENV_PATH = _base / ".env"
    loaded = load_dotenv(dotenv_path=ENV_PATH)
    if not loaded and hasattr(sys, "_MEIPASS"):
        _mei_env = Path(sys._MEIPASS) / ".env"
        if _mei_env.exists():
            loaded = load_dotenv(dotenv_path=_mei_env)
else:
    ENV_PATH = Path(__file__).resolve().parent / ".env"
    loaded = load_dotenv(dotenv_path=ENV_PATH)


def get_base_dir():
    """Returns the base application directory where config.json and .env reside."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_credentials():
    """Dynamically resolves and returns (korber_url, username, password).
    Checks:
    1. config.json (saved via UI Settings)
    2. os.environ
    3. .env file
    """
    base_dir = get_base_dir()
    cfg_path = base_dir / "config.json"
    url = ""
    user = ""
    pwd = ""

    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                user = data.get("korber_user", "").strip()
                pwd = data.get("korber_pass", "").strip()
                url = data.get("korber_url", "").strip()
        except Exception:
            pass

    if not user:
        user = os.environ.get("KORBER_USER", "").strip()
    if not pwd:
        pwd = os.environ.get("KORBER_PASS", "").strip()
    if not url:
        url = os.environ.get("KORBER_URL", "").strip() or "https://lopwaprodweb.koerbercloud.com/core/Default.html"

    return url, user, pwd


def save_credentials(username, password, url=None):
    """Saves user-configured Körber credentials to config.json and active runtime environment."""
    base_dir = get_base_dir()
    cfg_path = base_dir / "config.json"
    data = {}

    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    data["korber_user"] = str(username).strip()
    data["korber_pass"] = str(password).strip()
    if url:
        data["korber_url"] = str(url).strip()
    elif "korber_url" not in data:
        data["korber_url"] = "https://lopwaprodweb.koerbercloud.com/core/Default.html"

    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        log.warning(f"Could not save credentials to {cfg_path}: {e}")

    # Update runtime environment
    os.environ["KORBER_USER"] = data["korber_user"]
    os.environ["KORBER_PASS"] = data["korber_pass"]
    os.environ["KORBER_URL"] = data["korber_url"]


KORBER_URL, USERNAME, PASSWORD = get_credentials()


def open_new_browser(headless: bool = False, profile_name: str = "default"):
    """Launches a Chrome browser instance using a dedicated automation
    profile (not incognito, and not your everyday Default profile).

    profile_name: which isolated profile folder to use. Pass a different
    name for each browser session you want to run *at the same time*
    (e.g. "lane_a" / "lane_b") -- every session sharing a profile_name
    shares one profile folder, and this function assumes it's the only
    thing using that folder at that moment (see the lock-clearing note
    below), so two concurrent sessions MUST use different profile_name
    values or they will crash each other.

    Why a dedicated profile instead of --incognito:
    Incognito disables things like cached site data / extensions and can
    make some sites (especially heavy SPA sites like this Kendo/Knockout
    app) load noticeably slower on every single run, since nothing is ever
    cached between sessions.

    Why a *dedicated* profile instead of your normal Chrome profile:
    If this points at the same profile directory your everyday Chrome
    window uses, Selenium will fail with
    "SessionNotCreatedException: session not created" whenever your
    regular Chrome is already open, because Chrome refuses to let a second
    process attach to a profile directory that's already locked by a
    running instance. A separate profile folder avoids that entirely and
    still gets you the caching benefits (and you can log into Körber once
    here and stay logged in across runs, if the site supports that).
    """
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--start-maximized")

    # Dedicated profile folder, separate from your everyday Chrome profile
    # AND separate per profile_name, so that two browsers can be open at
    # once (e.g. two lanes in the multi-tool shell) without fighting over
    # the same profile directory. Lives next to this script so it's easy
    # to find/delete if you ever want to reset it (e.g. if login state
    # gets stuck).
    safe_name = "".join(c for c in profile_name if c.isalnum() or c in ("-", "_")) or "default"
    if getattr(sys, "frozen", False):
        _prof_base = Path(sys.executable).resolve().parent
    else:
        _prof_base = Path(__file__).resolve().parent
    profile_dir = _prof_base / f"chrome_automation_profile_{safe_name}"
    profile_dir.mkdir(exist_ok=True)

    # If the browser was closed by hand (clicking the X) instead of via
    # driver.quit(), Chrome can leave "Singleton*" lock files behind that
    # tell the next launch "this profile is already in use" -> Chrome then
    # refuses to start, which Selenium surfaces as
    # SessionNotCreatedException. Since this profile folder is only ever
    # used by ONE bot session at a time (one profile_name = one lane =
    # one browser), it's safe to clear these before launching *that
    # lane's* browser -- it is NOT safe to clear another lane's lock
    # files, which is why each profile_name gets its own folder above.
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lock_path = profile_dir / lock_name
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning(f"Could not remove stale lock file {lock_path}: {e}")

    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")

    # webdriver-manager keeps its own file lock at ~/.wdm/.wdm-lock-<name>
    # while it checks/downloads chromedriver, to stop two concurrent
    # processes from clobbering the same download. If a previous browser
    # launch got killed abruptly mid-download (Terminate Session, Restart
    # App, the process being closed, a crash, etc.), that lock file can be
    # left behind with nothing left to ever release it -- every future
    # launch then just hangs waiting for it and eventually raises
    # "TimeoutError: Timed out waiting for webdriver-manager lock: ...".
    # Same root cause as the Chrome profile Singleton* locks above, same
    # fix: since this bot only ever does one browser-opening operation at
    # a time, it's always safe to clear a stale lock before installing.
    wdm_lock_dir = Path.home() / ".wdm"
    if wdm_lock_dir.is_dir():
        for lock_path in wdm_lock_dir.glob(".wdm-lock*"):
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                log.warning(f"Could not remove stale webdriver-manager lock {lock_path}: {e}")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def login(driver, username=None, password=None, url=None):
    dyn_url, dyn_user, dyn_pwd = get_credentials()
    target_url = url or dyn_url or "https://lopwaprodweb.koerbercloud.com/core/Default.html"
    target_user = username or dyn_user
    target_pwd = password or dyn_pwd

    if not target_user or not target_pwd:
        raise ValueError(
            "Körber Username or Password is not configured.\n"
            "Please go to Settings (⚙) in EFL NEXUS to enter and save your login credentials."
        )

    wait = WebDriverWait(driver, 20)
    driver.get(target_url)
    log.info(f"Opened {target_url} for user '{target_user}'")

    # This page is built on Kendo UI / Knockout (custom <hj-textbox> elements
    # wrapping the real <input>). There is no plain id="username" — instead
    # we locate the inner input via the wrapping element's data-hj-test-id,
    # or fall back to matching on the placeholder text.
    try:
        username_field = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "hj-textbox[data-hj-test-id='username'] input")
            )
        )
    except TimeoutException:
        username_field = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input.k-textbox[placeholder='User Name']")
            )
        )

    username_field.clear()
    username_field.send_keys(target_user)

    # Confirmed: password field uses <hj-password-textbox> (a different
    # custom tag from the username field's <hj-textbox>).
    try:
        password_field = driver.find_element(
            By.CSS_SELECTOR, "hj-password-textbox[data-hj-test-id='password'] input"
        )
    except NoSuchElementException:
        password_field = driver.find_element(
            By.CSS_SELECTOR, "input[type='password']"
        )

    password_field.clear()
    password_field.send_keys(target_pwd)

    # Confirmed: login button is <hj-button data-hj-test-id="actionButton">
    # wrapping a <button class="k-button"> with a <span>Login</span> inside.
    try:
        login_button = driver.find_element(
            By.CSS_SELECTOR, "hj-button[data-hj-test-id='actionButton'] button"
        )
    except NoSuchElementException:
        login_button = driver.find_element(
            By.XPATH, "//hj-button//span[text()='Login']/ancestor::button"
        )

    login_button.click()
    log.info("Submitted login form")

    # TODO: replace with a real element that only appears after successful login
    # e.g. a dashboard element, menu, or logged-in username display
    time.sleep(3)
    log.info("Login step complete — verify visually for now until we confirm a post-login element")


if __name__ == "__main__":
    missing = [name for name, val in [("KORBER_URL", KORBER_URL), ("KORBER_USER", USERNAME), ("KORBER_PASS", PASSWORD)] if not val]
    if missing:
        raise SystemExit(
            f"Missing: {', '.join(missing)}\n"
            f"Looked for .env at: {ENV_PATH}\n"
            f".env file found and loaded: {loaded}\n"
            f"Fix: make sure .env sits next to this script, is named exactly '.env', "
            f"and contains KORBER_URL / KORBER_USER / KORBER_PASS with no quotes around values."
        )

    driver = open_new_browser(headless=False)
    try:
        login(driver)
        input("Press Enter to close the browser...")  # keeps window open so you can see the result
    finally:
        driver.quit()
