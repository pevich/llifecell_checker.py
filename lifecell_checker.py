import os
import re
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

URL = "https://my-ambassador.lifecell.ua"

INPUT_FILE = "numbers.txt"
VALID_FILE = "valid.txt"
UNKNOWN_FILE = "unknown.txt"

WAIT_LOGIN_SECONDS = 600
WAIT_UI_SECONDS = 40


def sanitize_numbers(lines):
    out = []
    for s in lines:
        s = re.sub(r"\D+", "", s.strip())
        if not s:
            continue
        if len(s) == 9:
            out.append(s)
        elif s.startswith("380") and len(s) == 12:
            out.append(s[3:])
        else:
            out.append(s)
    return out


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Lifecell LTE Checker")
        self.root.geometry("720x420")
        self.root.minsize(720, 420)

        self.status_var = tk.StringVar(value="Готово. Натисни «Почати»")
        self.progress_var = tk.StringVar(value="0 / 0")

        ttk.Label(root, text="Lifecell LTE Checker", font=("Segoe UI", 18, "bold")).pack(pady=(12, 6))
        ttk.Label(
            root,
            text="numbers.txt: тільки цифри ПІСЛЯ 380 (наприклад 935180140)\n"
                 "Після запуску увійди вручну (логін/пароль/SMS).",
            justify="center"
        ).pack(pady=(0, 8))

        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=14, pady=(4, 6))
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        ttk.Label(bar, textvariable=self.progress_var).pack(side="right")

        btns = ttk.Frame(root)
        btns.pack(side="bottom", fill="x", padx=14, pady=(8, 14))
        self.start_btn = ttk.Button(btns, text="▶ Почати", command=self.start)
        self.start_btn.pack(side="left")

        self.log_box = tk.Text(root, height=12, wrap="word")
        self.log_box.pack(side="top", fill="both", expand=True, padx=14, pady=(6, 6))
        self.log_box.configure(state="disabled")

        self.worker = None

    def log(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.root.update_idletasks()

    def set_status(self, msg: str):
        self.status_var.set(msg)
        self.root.update_idletasks()

    def set_progress(self, a: int, b: int):
        self.progress_var.set(f"{a} / {b}")
        self.root.update_idletasks()

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.start_btn.configure(state="disabled")
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    # ----------------- Selenium helpers -----------------

    def js_click(self, driver, el):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.15)
        driver.execute_script("arguments[0].click();", el)

    def wait_login_ready(self, wait_login):
        # Ждём появления "Клієнт" (после логина)
        return wait_login.until(EC.element_to_be_clickable((
            By.XPATH, "//div[contains(@class,'label') and normalize-space(text())='Клієнт']"
        )))

    def ensure_client_or_input(self, driver, wait_ui):
        """
        1) Пробує натиснути 'Клієнт'
        2) Якщо 'Клієнт' не знайдено — перевіряє, чи вже є поле msisdn
        3) Якщо поле є — ок, працюємо далі
        """
        # швидка спроба "Клієнт"
        try:
            short_wait = WebDriverWait(driver, 3)
            client = short_wait.until(EC.element_to_be_clickable((
                By.XPATH, "//div[contains(@class,'label') and normalize-space(text())='Клієнт']"
            )))
            self.js_click(driver, client)
            time.sleep(0.25)
        except Exception:
            pass

        # у будь-якому випадку чекаємо поле
        wait_ui.until(EC.presence_of_element_located((
            By.XPATH, "//div[contains(@class,'mat-form-field-infix')][.//input[@id='msisdn']]"
        )))
        wait_ui.until(EC.visibility_of_element_located((By.ID, "msisdn")))
        time.sleep(0.15)

    def click_infix_then_get_input(self, driver, wait_ui):
        # Кликаем по infix (обязательно для твоего сайта), потом получаем input заново
        infix = wait_ui.until(EC.element_to_be_clickable((
            By.XPATH, "//div[contains(@class,'mat-form-field-infix')][.//input[@id='msisdn']]"
        )))
        self.js_click(driver, infix)
        time.sleep(0.15)
        inp = wait_ui.until(EC.visibility_of_element_located((By.ID, "msisdn")))
        return inp

    # ✅ Angular-friendly setter + InputEvent
    def set_msisdn_value_js(self, driver, inp, full_number):
        driver.execute_script(
            """
            const el = arguments[0];
            const val = arguments[1];

            el.focus();

            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, val);

            const ev = new InputEvent('input', { bubbles: true, cancelable: true, data: val, inputType: 'insertText' });
            el.dispatchEvent(ev);

            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            inp, full_number
        )

    # ✅ clear via setter + 4 retries + verify value
    def type_number_stable(self, driver, wait_ui, number9):
        full = "380" + number9

        for attempt in range(1, 5):
            try:
                inp = self.click_infix_then_get_input(driver, wait_ui)

                # очистка через native setter
                driver.execute_script(
                    """
                    const el = arguments[0];
                    el.focus();
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, '');
                    el.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true, data: '', inputType: 'deleteContentBackward' }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    """,
                    inp
                )
                time.sleep(0.15)

                # ставимо значення
                self.set_msisdn_value_js(driver, inp, full)
                time.sleep(0.25)

                current = inp.get_attribute("value") or ""
                cur_digits = re.sub(r"\D+", "", current)

                if cur_digits.endswith(full) or cur_digits.endswith(number9):
                    return True

                self.log(f"  ⚠ Ввід не підтвердився, спроба {attempt}/4 (value='{current}')")
                time.sleep(0.35)

            except (StaleElementReferenceException, TimeoutException):
                self.log(f"  ⚠ Stale/Timeout на вводі, спроба {attempt}/4")
                time.sleep(0.5)

        return False

    def click_search(self, driver, wait_ui):
        btn = wait_ui.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and contains(normalize-space(.),'Пошук')]]"
        )))
        self.js_click(driver, btn)

    def click_back(self, driver, wait_ui):
        btn = wait_ui.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//mat-icon[normalize-space(text())='arrow_back']]"
        )))
        self.js_click(driver, btn)
        time.sleep(0.8)

    def is_unknown(self, driver):
        return len(driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'text') and contains(@class,'unknown') and contains(normalize-space(.),'UNKNOWN')]"
        )) > 0

    def is_lte_no_support(self, driver):
        return len(driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'header') and contains(@class,'device-no-support') and contains(normalize-space(.),'LTE')]"
        )) > 0

    def is_lte_support(self, driver):
        return len(driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'header') and contains(@class,'support') and contains(normalize-space(.),'LTE')]"
        )) > 0

    def register_flow(self, driver, wait_ui):
        reg = wait_ui.until(EC.element_to_be_clickable((
            By.XPATH, "//div[contains(@class,'label') and contains(normalize-space(.),'Реєстрація стартового пакету')]"
        )))
        self.js_click(driver, reg)

        reg_btn = wait_ui.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and contains(normalize-space(.),'Зареєструвати')]]"
        )))
        self.js_click(driver, reg_btn)

        ok_btn = wait_ui.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Ок')]"
        )))
        self.js_click(driver, ok_btn)
        time.sleep(0.5)

    # ----------------- Main run -----------------

    def run(self):
        driver = None
        try:
            if not os.path.exists(INPUT_FILE):
                messagebox.showerror("Помилка", f"Не знайдено {INPUT_FILE} поруч з програмою.")
                return

            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                nums = sanitize_numbers(f.readlines())

            total = len(nums)
            if total == 0:
                messagebox.showerror("Помилка", "numbers.txt порожній або без коректних номерів.")
                return

            self.set_progress(0, total)
            self.set_status("Запуск браузера…")
            self.log("Відкриваю Chrome та сайт…")

            options = webdriver.ChromeOptions()
            options.add_argument("--start-maximized")
            driver = webdriver.Chrome(options=options)

            wait_login = WebDriverWait(driver, WAIT_LOGIN_SECONDS)
            wait_ui = WebDriverWait(driver, WAIT_UI_SECONDS)

            driver.get(URL)

            self.set_status("Очікую авторизацію…")
            self.log("Увійди вручну (логін/пароль/SMS). Я продовжу, коли з’явиться «Клієнт».")

            self.wait_login_ready(wait_login)
            self.log("Авторизацію підтверджено ✅")

            for i, n in enumerate(nums, start=1):
                self.set_progress(i, total)
                self.set_status(f"Перевірка: 380{n}")
                self.log(f"[{i}/{total}] Номер: 380{n}")

                # ✅ Тепер: якщо "Клієнт" не знайдено — працюємо через поле
                self.ensure_client_or_input(driver, wait_ui)

                ok = self.type_number_stable(driver, wait_ui, n)
                if not ok:
                    self.log("  ⛔ Не вдалося ввести номер у поле. Записую як UNKNOWN і йду далі.")
                    with open(UNKNOWN_FILE, "a", encoding="utf-8") as out:
                        out.write(n + "\n")
                    continue

                try:
                    self.click_search(driver, wait_ui)
                except Exception:
                    self.log("  ⛔ Не натиснувся «Пошук». UNKNOWN + назад.")
                    with open(UNKNOWN_FILE, "a", encoding="utf-8") as out:
                        out.write(n + "\n")
                    try:
                        self.click_back(driver, wait_ui)
                        time.sleep(0.6)
                    except Exception:
                        pass
                    continue

                deadline = time.time() + 20
                while time.time() < deadline:
                    if self.is_unknown(driver) or self.is_lte_no_support(driver) or self.is_lte_support(driver):
                        break
                    time.sleep(0.25)

                if self.is_unknown(driver) or self.is_lte_no_support(driver):
                    if self.is_unknown(driver):
                        self.log("  → UNKNOWN")
                    else:
                        self.log("  → LTE (не підтримує)")

                    with open(UNKNOWN_FILE, "a", encoding="utf-8") as out:
                        out.write(n + "\n")

                    try:
                        self.click_back(driver, wait_ui)
                        time.sleep(0.6)
                    except Exception:
                        pass
                    continue

                if self.is_lte_support(driver):
                    self.log("  → LTE (підтримує) → Реєстрація…")
                    with open(VALID_FILE, "a", encoding="utf-8") as out:
                        out.write(n + "\n")

                    try:
                        self.register_flow(driver, wait_ui)
                        self.log("  ✅ Зареєстровано + ОК")
                    except Exception:
                        self.log("  ⚠ Реєстрація/ОК не вдалася — йду назад.")

                    try:
                        self.click_back(driver, wait_ui)
                        time.sleep(0.6)
                    except Exception:
                        pass
                    continue

                self.log("  ⚠ Статус не визначив — UNKNOWN")
                with open(UNKNOWN_FILE, "a", encoding="utf-8") as out:
                    out.write(n + "\n")
                try:
                    self.click_back(driver, wait_ui)
                    time.sleep(0.6)
                except Exception:
                    pass

            self.set_status("Готово ✅")
            self.log("Завершено. Файли: valid.txt / unknown.txt")

        except Exception as e:
            messagebox.showerror("Помилка", str(e))
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            self.start_btn.configure(state="normal")


if __name__ == "__main__":
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()
