from __future__ import annotations

import calendar
import glob
import os
import time
from datetime import datetime
from pathlib import Path

from .paths import default_group, downloads_dir, project_downloads_dir, raw_dir


def read_env_file(path: str | Path = ".env") -> dict[str, str]:
    env_path = Path(path)
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_config(group_name: str | None = None) -> dict[str, str]:
    file_values = read_env_file()
    group = group_name or default_group()
    return {
        "username": os.getenv("EDC_USERNAME") or file_values.get("EDC_USERNAME", ""),
        "password": os.getenv("EDC_PASSWORD") or file_values.get("EDC_PASSWORD", ""),
        "group": group,
        "chromedriver": os.getenv("EDC_CHROMEDRIVER") or file_values.get("EDC_CHROMEDRIVER", "/usr/bin/chromedriver"),
        "chrome_binary": os.getenv("EDC_CHROME_BINARY") or file_values.get("EDC_CHROME_BINARY", ""),
        "download_dir": os.getenv("EDC_DOWNLOAD_DIR") or file_values.get("EDC_DOWNLOAD_DIR", str(raw_dir(group))),
        "chrome_profile": os.getenv("EDC_CHROME_PROFILE") or file_values.get("EDC_CHROME_PROFILE", str(project_downloads_dir() / "chrome-profile")),
    }


def download_month(month: int, year: int, output_name: str | None = None) -> Path:
    return download_months([(month, year, output_name)])[0]


def download_months(months: list[tuple[int, int, str | None]], group_name: str | None = None) -> list[Path]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:
        raise RuntimeError("Selenium is not installed. Install it with: python3 -m pip install selenium") from exc

    config = get_config(group_name)
    missing = [key for key in ("username", "password") if not config[key]]
    if missing:
        raise RuntimeError(f"Missing EDC config values: {', '.join(missing)}. Fill .env first.")

    download_dir = Path(config["download_dir"]).resolve()
    download_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = (downloads_dir(config["group"]) / "debug").resolve()
    debug_dir.mkdir(parents=True, exist_ok=True)
    chrome_profile = Path(config["chrome_profile"]).resolve()
    chrome_profile.mkdir(parents=True, exist_ok=True)

    options = Options()
    options.add_experimental_option("prefs", {
        "download.default_directory": str(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    })
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-data-dir={chrome_profile}")
    options.add_argument("--profile-directory=Default")
    if config["chrome_binary"]:
        options.binary_location = config["chrome_binary"]

    driver = webdriver.Chrome(service=Service(config["chromedriver"]), options=options)
    wait = WebDriverWait(driver, 20)

    try:
        _login(driver, wait, config, debug_dir)
        return [
            _download_month_in_session(driver, wait, config, download_dir, debug_dir, month, year, output_name)
            for month, year, output_name in months
        ]
    except Exception:
        _debug_capture(driver, debug_dir, "99-error")
        raise
    finally:
        _logout_if_authenticated(driver)
        driver.quit()


def _login(driver: object, wait: object, config: dict[str, str], debug_dir: Path) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    driver.get("https://portal.edc-cr.cz/")
    _debug_capture(driver, debug_dir, "01-home")
    if not _is_authenticated(driver.page_source):
        _click_public_login(driver, wait)
        wait.until(EC.presence_of_element_located((By.XPATH, "//input[@id='username']"))).send_keys(config["username"])
        driver.find_element(By.XPATH, "//input[@id='password']").send_keys(config["password"])
        _debug_capture(driver, debug_dir, "02-login-filled")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@id='kc-login']"))).click()
        _ensure_authenticated(driver, wait, config["username"], config["password"], debug_dir)
    _debug_capture(driver, debug_dir, "03-after-login")
    if not _is_authenticated(driver.page_source) and not _verify_portal_access(driver, wait, debug_dir):
        raise RuntimeError("EDC login did not create an authenticated portal session")


def _download_month_in_session(
    driver: object,
    wait: object,
    config: dict[str, str],
    download_dir: Path,
    debug_dir: Path,
    month: int,
    year: int,
    output_name: str | None = None,
) -> Path:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    output_name = output_name or f"edc-{year}-{month:02d}.csv"
    driver.get("https://portal.edc-cr.cz/sprava-dat/zobrazeni-dat")
    wait.until(lambda item: "zobrazeni-dat" in item.current_url)
    wait.until(lambda item: "Vyberte" in item.page_source or "Skupina sdílení" in item.page_source)
    _hide_chat(driver)
    _debug_capture(driver, debug_dir, f"04-data-page-{year}-{month:02d}")
    available_groups = _get_sharing_groups(driver, wait)
    _write_available_groups(debug_dir, available_groups)
    if not config["group"].strip():
        raise RuntimeError(
                "Missing EDC_DEFAULT_GROUP/EDC_GROUP. Available sharing groups were written to "
            f"{debug_dir / 'available-groups.txt'}"
        )
    _select_sharing_group(driver, wait, config["group"], available_groups)
    _debug_capture(driver, debug_dir, f"05-group-selected-{year}-{month:02d}")

    export_type = "DAILY" if _use_daily_export(month, year) else "MONTHLY"
    _select_export_type(driver, wait, export_type)
    _fill_date(driver, wait, "dateFrom", f"01.{month:02d}.{year:04d}")
    last_day = calendar.monthrange(year, month)[1]
    _fill_date(driver, wait, "dateTo", f"{last_day:02d}.{month:02d}.{year:04d}")
    _debug_capture(driver, debug_dir, f"06-export-ready-{year}-{month:02d}")

    wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Export']"))).click()
    file_name = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@id='fileName']")))
    file_name.clear()
    file_name.send_keys(Path(output_name).stem)
    wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Exportovat']"))).click()
    time.sleep(10)
    wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Přejít na reporty']"))).click()
    wait.until(EC.element_to_be_clickable((By.XPATH, "//table[contains(@class,'MuiTable-root')]//tr[1]//p[text()='Stáhnout']"))).click()
    time.sleep(4)

    files = [Path(item) for item in glob.glob(str(download_dir / "*")) if Path(item).is_file()]
    newest = max(files, key=lambda item: item.stat().st_ctime)
    target_path = download_dir / output_name
    if target_path.exists():
        target_path.unlink()
    newest.rename(target_path)
    return target_path


def _fill_date(driver: object, wait: object, name: str, value: str) -> None:
    field = wait.until(lambda _: driver.find_element("xpath", f"//input[@name='{name}']"))
    field.click()
    field.send_keys("\ue009" + "a")
    field.send_keys(value)


def _select_export_type(driver: object, wait: object, export_type: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    labels = {
        "DAILY": "Denní hodnoty",
        "MONTHLY": "Měsíční hodnoty",
    }
    label = labels[export_type]
    option = wait.until(EC.element_to_be_clickable((
        By.XPATH,
        f"//label[.//span[normalize-space()='{label}']]",
    )))
    driver.execute_script("arguments[0].click()", option)
    time.sleep(1)
    selected = driver.find_element(By.XPATH, f"//input[@name='viewTypeRadios' and @value='{export_type}']")
    if not selected.is_selected():
        driver.execute_script("arguments[0].click()", selected)
        time.sleep(1)
    if not selected.is_selected():
        raise RuntimeError(f"Unable to select EDC export type {label!r}")


def _hide_chat(driver: object) -> None:
    try:
        driver.execute_script("document.querySelector('#daktela-web')?.remove()")
    except Exception:
        pass


def _return_to_app_if_needed(driver: object) -> None:
    from selenium.webdriver.common.by import By

    try:
        links = driver.find_elements(By.XPATH, "//a[contains(normalize-space(), 'Zpět na aplikaci')]")
        if links:
            links[0].click()
            time.sleep(3)
    except Exception:
        pass


def _click_public_login(driver: object, wait: object) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    button = wait.until(EC.element_to_be_clickable((
        By.XPATH,
        "//button[contains(normalize-space(), 'Přihlášení')]",
    )))
    button.click()


def _ensure_authenticated(driver: object, wait: object, username: str, password: str, debug_dir: Path) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    for attempt in range(12):
        time.sleep(3)
        _return_to_app_if_needed(driver)
        wait.until(lambda item: item.execute_script("return document.readyState") == "complete")

        page = driver.page_source
        if _is_authenticated(page):
            return
        if (attempt >= 2 or "code=" not in driver.current_url) and _verify_portal_access(driver, wait, debug_dir):
            return
        if "Uživatel je již přihlášen" in page:
            _return_to_app_if_needed(driver)
            time.sleep(3)
            if _is_authenticated(driver.page_source):
                return
            if _verify_portal_access(driver, wait, debug_dir):
                return
            raise RuntimeError(
                "EDC login blocked: Uživatel je již přihlášen v jiném sezení. "
                "Zkuste to znovu po automatickém ukončení odpojených sezení, obvykle do 15 minut."
            )

        username_fields = [item for item in driver.find_elements(By.XPATH, "//input[@id='username']") if item.is_displayed()]
        password_fields = [item for item in driver.find_elements(By.XPATH, "//input[@id='password']") if item.is_displayed()]
        if username_fields and password_fields:
            username_field = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@id='username']")))
            username_field.clear()
            username_field.send_keys(username)
            password_field = password_fields[0]
            password_field.clear()
            password_field.send_keys(password)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@id='kc-login']"))).click()
            continue
        if "Registrace / Přihlášení" in page:
            _click_public_login(driver, wait)
            continue
        if attempt in (3, 7, 11):
            _debug_capture(driver, debug_dir, f"login-wait-{attempt + 1}")

    raise RuntimeError("EDC login did not create an authenticated portal session")


def _is_authenticated(page_source: str) -> bool:
    return "Standardní přístup" in page_source or "Odhlásit" in page_source


def _verify_portal_access(driver: object, wait: object, debug_dir: Path) -> bool:
    if "portal.edc-cr.cz" not in driver.current_url or "sso.portal.edc-cr.cz" in driver.current_url:
        return False
    try:
        driver.get("https://portal.edc-cr.cz/sprava-dat/zobrazeni-dat")
        wait.until(lambda item: item.execute_script("return document.readyState") == "complete")
        wait.until(lambda item: (
            "zobrazeni-dat" in item.current_url
            and ("Vyberte" in item.page_source or "Skupina sdílení" in item.page_source)
        ) or "Registrace / Přihlášení" in item.page_source)
        _debug_capture(driver, debug_dir, "03-portal-access-check")
        return "zobrazeni-dat" in driver.current_url and (
            "Vyberte" in driver.page_source or "Skupina sdílení" in driver.page_source
        )
    except Exception:
        return False


def _logout_if_authenticated(driver: object) -> None:
    from selenium.webdriver.common.by import By

    try:
        if _is_authenticated(driver.page_source):
            menu_buttons = driver.find_elements(By.XPATH, "//button[@title='Menu']")
            if menu_buttons:
                menu_buttons[0].click()
                time.sleep(1)
            logout_items = driver.find_elements(By.XPATH, "//*[contains(normalize-space(), 'Odhlásit')]")
            if logout_items:
                logout_items[0].click()
                time.sleep(2)
        driver.get("https://sso.portal.edc-cr.cz/auth/realms/edc/protocol/openid-connect/logout?redirect_uri=https%3A%2F%2Fportal.edc-cr.cz%2F")
        time.sleep(2)
    except Exception:
        pass


def _open_sharing_group_select(driver: object, wait: object) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    sse_radio = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@name='inputParameterRadio' and @value='SSE']")))
    if not sse_radio.is_selected():
        driver.execute_script("arguments[0].click()", sse_radio)
        time.sleep(1)

    wait.until(EC.element_to_be_clickable((
        By.XPATH,
        "//input[@name='sseId']/ancestor::*[contains(@class, 'MuiFormControl-root')]",
    ))).click()
    time.sleep(2)


def _get_sharing_groups(driver: object, wait: object) -> list[str]:
    from selenium.webdriver.common.by import By

    _open_sharing_group_select(driver, wait)
    groups = [item.text.strip() for item in driver.find_elements(By.XPATH, "//li[@role='option']") if item.text.strip()]
    # Close the popup so the following click starts from a stable state.
    try:
        driver.switch_to.active_element.send_keys("\ue00c")  # Escape
    except Exception:
        pass
    return groups


def _write_available_groups(debug_dir: Path, groups: list[str]) -> None:
    content = "\n".join(groups) if groups else "No sharing groups found."
    (debug_dir / "available-groups.txt").write_text(content + "\n", encoding="utf-8")
    print("Available EDC sharing groups:")
    for group in groups:
        print(f"- {group}")


def _select_sharing_group(driver: object, wait: object, group_name: str, available_groups: list[str] | None = None) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    wanted = group_name.strip()
    if not wanted:
        raise RuntimeError("EDC_DEFAULT_GROUP/EDC_GROUP is empty")

    if available_groups is not None and wanted not in available_groups:
        raise RuntimeError(
            f"EDC sharing group {wanted!r} was not found. "
            "See the active downloads debug directory for available values."
        )

    _open_sharing_group_select(driver, wait)
    options = driver.find_elements(By.XPATH, "//li[@role='option']")
    if options:
        target = next((item for item in options if item.text.strip() == wanted), None)
        if target is None:
            raise RuntimeError(
                f"EDC sharing group {wanted!r} was not found. "
                "See the active downloads debug directory for available values."
            )
        target.click()
    else:
        # Fallback for autocomplete implementations that only react to keyboard input.
        active = driver.switch_to.active_element
        active.send_keys(wanted)
        time.sleep(1)
        active.send_keys(Keys.ARROW_DOWN)
        active.send_keys(Keys.ENTER)
        time.sleep(1)

    selected_value = driver.find_element(By.XPATH, "//input[@name='sseId']").get_attribute("value")
    if not selected_value:
        raise RuntimeError(f"Unable to select EDC sharing group {wanted!r}")


def _debug_capture(driver: object, debug_dir: Path, name: str) -> None:
    safe_name = name.replace("/", "-")
    try:
        driver.save_screenshot(str(debug_dir / f"{safe_name}.png"))
    except Exception:
        pass
    try:
        (debug_dir / f"{safe_name}.html").write_text(driver.page_source, encoding="utf-8")
    except Exception:
        pass
    try:
        (debug_dir / f"{safe_name}.txt").write_text(
            f"url={driver.current_url}\ntitle={driver.title}\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _use_daily_export(month: int, year: int) -> bool:
    now = datetime.now()
    return month == now.month and year == now.year
