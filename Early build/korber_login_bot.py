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

# Look for .env in the same folder as this script (not the current working
# directory), so it works no matter where you run "python korber_login_bot.py" from.
ENV_PATH = Path(__file__).resolve().parent / ".env"
loaded = load_dotenv(dotenv_path=ENV_PATH)

if not loaded:
    log.warning(f"Could not find or load .env at: {ENV_PATH}")
    log.warning("Check: (1) the file is literally named '.env' with no extra extension "
                "like .env.txt, (2) it's in the same folder as this script.")

KORBER_URL = os.environ.get("KORBER_URL")
USERNAME = os.environ.get("KORBER_USER")
PASSWORD = os.environ.get("KORBER_PASS")


def open_new_browser(headless: bool = False):
    """Launches a Chrome browser instance using a dedicated automation
    profile (not incognito, and not your everyday Default profile).

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

    # Dedicated profile folder, separate from your everyday Chrome profile.
    # Lives next to this script so it's easy to find/delete if you ever
    # want to reset it (e.g. if login state gets stuck).
    profile_dir = Path(__file__).resolve().parent / "chrome_automation_profile"
    profile_dir.mkdir(exist_ok=True)

    # If the browser was closed by hand (clicking the X) instead of via
    # driver.quit(), Chrome can leave "Singleton*" lock files behind that
    # tell the next launch "this profile is already in use" -> Chrome then
    # refuses to start, which Selenium surfaces as
    # SessionNotCreatedException. Since this profile folder is only ever
    # used by this one bot (never two runs at once), it's always safe to
    # clear these before launching.
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

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def login(driver):
    wait = WebDriverWait(driver, 20)
    driver.get(KORBER_URL)
    log.info(f"Opened {KORBER_URL}")

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
    username_field.send_keys(USERNAME)

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
    password_field.send_keys(PASSWORD)

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
