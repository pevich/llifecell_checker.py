import os
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://my-ambassador.lifecell.ua"

NUMBERS_FILE = "numbers.txt"
VALID_FILE = "valid.txt"
TRASH_FILE = "trash.txt"

WAIT_LOGIN_SECONDS = 600
WAIT_UI_SECONDS = 12
WAIT_RESULT_SECONDS = 9
POLL = 0.05


def load_numbers():
    if not os.path.exists(NUMBERS_FILE):
        return []
    out = []
    with open(NUMBERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            s = re.sub(r"\D+", "", line.strip())
            if not s:
                continue
            if len(s) == 9:
                out.append(s)
            elif s.startswith("380") and len(s) == 12:
                out.append(s[3:])
            else:
                out.append(s)
    return out


def save_numbers(numbers):
    with open(NUMBERS_FILE, "w", encoding="utf-8") as f:
        for n in numbers:
            f.write(n + "\n")


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Lifecell Checker TURBO")
        self.root.geometry("780x480")

        self.status = tk.StringVar(value="Готово")
        self.progress = tk.StringVar(value="0 / 0")

        self.stop_event = threading.Event()
        self.worker = None

        ttk.Label(root, text="Lifecell Checker TURBO", font=("Segoe UI", 18, "bold")).pack(pady=10)

        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=14, pady=4)
        ttk.Label(bar, textvariable=self.status).pack(side="left")
        ttk.Label(bar, textvariable=self.progress).pack(side="right")

        btns = ttk.Frame(root)
        btns.pack(fill="x", padx=14, pady=6)
        self.btn_start = ttk.Button(btns, text="▶ Почати", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(btns, text="⏹ Стоп", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=10)

        self.log_box = tk.Text(root, height=16)
        self.log_box.pack(fill="both", expand=True, padx=14, pady=10)
        self.log_box.configure(state="disabled")

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.root.update_idletasks()

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.status.set("Зупинка...")

    # ---------- Selenium helpers ----------

    def js_click(self, driver, el):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        driver.execute_script("arguments[0].click();", el)

    def wait_client_button(self, driver):
        return WebDriverWait(driver, WAIT_UI_SECONDS, poll_frequency=POLL).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[contains(@class,'content')][.//div[contains(@class,'label') and normalize-space(.)='Клієнт']]"
            ))
        )

    def click_client(self, driver):
        self.js_click(driver, self.wait_client_button(driver))

    def wait_msisdn_ready(self, driver):
        wait = WebDriverWait(driver, WAIT_UI_SECONDS, poll_frequency=POLL)
        wait.until(EC.presence_of_element_located((By.ID, "msisdn")))
        wait.until(EC.element_to_be_clickable((By.ID, "msisdn")))
        return wait

    def ensure_client_form(self, driver):
        if len(driver.find_elements(By.ID, "msisdn")) > 0:
            return self.wait_msisdn_ready(driver)
        self.click_client(driver)
        return self.wait_msisdn_ready(driver)

    def set_number(self, driver, wait, number):
        inp = wait.until(EC.element_to_be_clickable((By.ID, "msisdn")))
        full = "380" + number
        driver.execute_script(
            """
            const el = arguments[0];
            const v = arguments[1];
            const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            el.focus();
            s.call(el,'');
            el.dispatchEvent(new InputEvent('input',{bubbles:true}));
            s.call(el,v);
            el.dispatchEvent(new InputEvent('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
            """,
            inp, full
        )

    def click_search(self, driver, wait):
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Пошук']]"
        )))
        self.js_click(driver, btn)

    # ✅ тільки перевірка "Реєстрація послуг"
    def has_services_menu(self, driver):
        return len(driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'menu-item-content')]//div[contains(@class,'label') and normalize-space(.)='Реєстрація послуг']"
        )) > 0

    # ✅ додаткова перевірка: чи є "Реєстрація стартового пакету" (саме як content->label)
    def has_start_pack(self, driver):
        return len(driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'content')][.//div[contains(@class,'label') and normalize-space(.)='Реєстрація стартового пакету']]"
        )) > 0

    def click_start_pack(self, driver, wait):
        el = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//div[contains(@class,'content')][.//div[contains(@class,'label') and normalize-space(.)='Реєстрація стартового пакету']]"
        )))
        self.js_click(driver, el)

    def click_register(self, driver, wait):
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Зареєструвати']]"
        )))
        self.js_click(driver, btn)

    def click_ok(self, driver, wait):
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Ок']]"
        )))
        self.js_click(driver, btn)

    def click_back_if_exists(self, driver):
        backs = driver.find_elements(By.XPATH, "//button[.//mat-icon[normalize-space(text())='arrow_back']]")
        if backs:
            self.js_click(driver, backs[0])
            return True
        return False

    def back_to_home_and_open_client(self, driver):
        """
        ✅ Повертаємось поки не побачимо кнопку Клієнт, потім тиснемо її, щоб знов було поле msisdn.
        """
        for _ in range(4):
            if len(driver.find_elements(By.ID, "msisdn")) > 0:
                return self.wait_msisdn_ready(driver)

            if len(driver.find_elements(By.XPATH,
                    "//div[contains(@class,'content')][.//div[contains(@class,'label') and normalize-space(.)='Клієнт']]")) > 0:
                self.click_client(driver)
                return self.wait_msisdn_ready(driver)

            if not self.click_back_if_exists(driver):
                break

        # fallback
        self.click_client(driver)
        return self.wait_msisdn_ready(driver)

    # ---------- MAIN ----------

    def run(self):
        numbers = load_numbers()
        if not numbers:
            messagebox.showerror("Помилка", "numbers.txt порожній.")
            return

        driver = webdriver.Chrome()
        wait_login = WebDriverWait(driver, WAIT_LOGIN_SECONDS, poll_frequency=POLL)

        driver.get(URL)
        self.log("Очікую логін...")

        wait_login.until(EC.presence_of_element_located((
            By.XPATH,
            "//div[contains(@class,'content')][.//div[contains(@class,'label') and normalize-space(.)='Клієнт']]"
        )))
        self.log("Авторизація OK")

        remaining = []
        total = len(numbers)

        try:
            for i, number in enumerate(numbers, 1):
                if self.stop_event.is_set():
                    break

                self.progress.set(f"{i} / {total}")
                self.status.set(f"380{number}")
                self.log(f"→ 380{number}")

                try:
                    wait = self.back_to_home_and_open_client(driver)

                    self.set_number(driver, wait, number)
                    self.click_search(driver, wait)

                    # даємо сторінці прогрузити меню/кнопки
                    WebDriverWait(driver, WAIT_RESULT_SECONDS, poll_frequency=POLL).until(lambda d: True)

                    # ✅ НОВА ЛОГІКА:
                    # Якщо є "Реєстрація послуг" І є "Реєстрація стартового пакету" -> тоді реєструємо
                    if self.has_services_menu(driver) and self.has_start_pack(driver):
                        self.log("  ✓ Є «Реєстрація послуг» + «Реєстрація стартового пакету» → реєструю…")
                        self.click_start_pack(driver, wait)
                        self.click_register(driver, wait)
                        self.click_ok(driver, wait)

                        with open(VALID_FILE, "a", encoding="utf-8") as f:
                            f.write(number + "\n")
                        self.log("  ✔ Зареєстровано → VALID (видалено з numbers.txt)")

                    else:
                        with open(TRASH_FILE, "a", encoding="utf-8") as f:
                            f.write(number + "\n")
                        self.log("  🗑 Нема потрібних елементів → TRASH")
                        remaining.append(number)

                    # ✅ завжди повернутись на форму клієнта для наступного номера
                    self.back_to_home_and_open_client(driver)

                except Exception:
                    with open(TRASH_FILE, "a", encoding="utf-8") as f:
                        f.write(number + "\n")
                    remaining.append(number)
                    try:
                        self.back_to_home_and_open_client(driver)
                    except Exception:
                        pass

            save_numbers(remaining)

        finally:
            try:
                driver.quit()
            except Exception:
                pass
            self.status.set("Готово")
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
