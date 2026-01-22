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

# TURBO
WAIT_UI_SECONDS = 10
POLL = 0.05

# після пошуку даємо час прогрузити меню
WAIT_RESULT_SECONDS = 9


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
        ttk.Label(root, text="numbers.txt → valid.txt / trash.txt", justify="center").pack()

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

        self.log_box = tk.Text(root, height=15)
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

    # ---------------- Selenium ----------------

    def js_click(self, driver, el):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        driver.execute_script("arguments[0].click();", el)

    def ensure_client(self, driver, wait):
        # якщо є "Клієнт" — натиснемо, якщо нема — працюємо на поточній сторінці
        try:
            client = WebDriverWait(driver, 1.5, poll_frequency=POLL).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'label') and normalize-space(.)='Клієнт']"))
            )
            self.js_click(driver, client)
        except Exception:
            pass

        # поле номера має бути доступне
        wait.until(EC.presence_of_element_located((By.ID, "msisdn")))
        wait.until(EC.element_to_be_clickable((By.ID, "msisdn")))

    def set_number(self, driver, wait, number9):
        inp = wait.until(EC.element_to_be_clickable((By.ID, "msisdn")))
        full = "380" + number9
        driver.execute_script(
            """
            const el = arguments[0];
            const v = arguments[1];
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            setter.call(el, '');
            el.dispatchEvent(new InputEvent('input',{bubbles:true}));
            setter.call(el, v);
            el.dispatchEvent(new InputEvent('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
            """,
            inp, full
        )

    def click_search(self, driver, wait):
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Пошук']]"
        )))
        self.js_click(driver, btn)

    # ✅ FIX: шукаємо "Реєстрація послуг" саме як елемент меню (menu-item-content -> label)
    def has_services_menu(self, driver):
        return len(driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'menu-item-content') and .//div[contains(@class,'label') and normalize-space(.)='Реєстрація послуг']]"
        )) > 0

    def wait_services_or_timeout(self, driver):
        WebDriverWait(driver, WAIT_RESULT_SECONDS, poll_frequency=POLL).until(
            lambda d: self.has_services_menu(d)
        )

    def open_services_menu(self, driver, wait):
        el = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//div[contains(@class,'menu-item-content') and .//div[contains(@class,'label') and normalize-space(.)='Реєстрація послуг']]"
        )))
        self.js_click(driver, el)

    def register_start_pack(self, driver, wait):
        # "Реєстрація стартового пакету"
        start_pack = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//div[contains(@class,'label') and contains(normalize-space(.),'Реєстрація стартового пакету')]"
        )))
        self.js_click(driver, start_pack)

        # "Зареєструвати"
        reg_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Зареєструвати']]"
        )))
        self.js_click(driver, reg_btn)

        # "Ок"
        ok_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Ок']]"
        )))
        self.js_click(driver, ok_btn)

    def go_back_to_client(self, driver, wait, times=1):
        """
        ✅ Гарантовано повертаємось назад.
        times=1: назад на результат/форму
        times=2: назад аж до сторінки де є "Клієнт" (як ти просив раніше в деяких кейсах)
        """
        for _ in range(times):
            btn = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//button[.//mat-icon[normalize-space(text())='arrow_back']]"
            )))
            self.js_click(driver, btn)

        # після повернення — дочекаємось або "Клієнт", або поля msisdn (щоб наступний номер не падав)
        try:
            WebDriverWait(driver, 4, poll_frequency=POLL).until(
                lambda d: len(d.find_elements(By.XPATH, "//div[contains(@class,'label') and normalize-space(.)='Клієнт']")) > 0
                          or len(d.find_elements(By.ID, "msisdn")) > 0
            )
        except Exception:
            pass

    # ---------------- MAIN ----------------

    def run(self):
        numbers = load_numbers()
        if not numbers:
            messagebox.showerror("Помилка", "numbers.txt порожній або не знайдено.")
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            return

        total = len(numbers)
        self.progress.set(f"0 / {total}")

        driver = None
        try:
            driver = webdriver.Chrome()
            wait_login = WebDriverWait(driver, WAIT_LOGIN_SECONDS, poll_frequency=POLL)
            wait = WebDriverWait(driver, WAIT_UI_SECONDS, poll_frequency=POLL)

            driver.get(URL)
            self.log("Очікую логін...")
            wait_login.until(EC.presence_of_element_located(
                (By.XPATH, "//div[contains(@class,'label') and normalize-space(.)='Клієнт']")
            ))
            self.log("Авторизація OK")

            remaining = []
            done = 0

            for number in numbers:
                if self.stop_event.is_set():
                    break

                done += 1
                self.progress.set(f"{done} / {total}")
                self.status.set(f"380{number}")
                self.log(f"→ 380{number}")

                try:
                    # завжди починаємо з екрану клієнта/поля
                    self.ensure_client(driver, wait)

                    # вводимо номер і шукаємо
                    self.set_number(driver, wait, number)
                    self.click_search(driver, wait)

                    # ✅ чекати саме меню "Реєстрація послуг"
                    try:
                        self.wait_services_or_timeout(driver)
                        # відкриваємо пункт меню "Реєстрація послуг"
                        self.open_services_menu(driver, wait)

                        # робимо реєстрацію стартового пакету
                        self.register_start_pack(driver, wait)

                        with open(VALID_FILE, "a", encoding="utf-8") as f:
                            f.write(number + "\n")
                        self.log("  ✔ Зареєстровано → VALID (видалено з numbers.txt)")

                        # ✅ КРИТИЧНО: після успіху ПОВЕРТАЄМОСЬ НАЗАД (щоб наступний номер не падав)
                        # ІНКОЛИ треба 2 рази — ставимо 2 для стабільності
                        try:
                            self.go_back_to_client(driver, wait, times=2)
                        except Exception:
                            try:
                                self.go_back_to_client(driver, wait, times=1)
                            except Exception:
                                pass

                        # НЕ додаємо в remaining => видалиться з numbers.txt
                        continue

                    except Exception:
                        # немає menu "Реєстрація послуг" → TRASH
                        with open(TRASH_FILE, "a", encoding="utf-8") as f:
                            f.write(number + "\n")
                        self.log("  🗑 Нема «Реєстрація послуг» → TRASH (залишив у numbers.txt)")

                        # ✅ ПОВЕРТАЄМОСЬ НАЗАД ДЛЯ НАСТУПНОГО НОМЕРА
                        try:
                            self.go_back_to_client(driver, wait, times=1)
                        except Exception:
                            pass

                        remaining.append(number)
                        continue

                except Exception:
                    with open(TRASH_FILE, "a", encoding="utf-8") as f:
                        f.write(number + "\n")
                    self.log("  🗑 Помилка на номері → TRASH (залишив у numbers.txt)")
                    remaining.append(number)
                    try:
                        self.go_back_to_client(driver, wait, times=2)
                    except Exception:
                        pass
                    continue

            # numbers.txt: лишаємо тільки НЕзареєстровані
            save_numbers(remaining)

            if self.stop_event.is_set():
                self.status.set("Зупинено ✅")
                self.log("⏹ Зупинено. numbers.txt оновлено (зареєстровані прибрані).")
            else:
                self.status.set("Готово ✅")
                self.log("Завершено. numbers.txt оновлено (зареєстровані прибрані).")

        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
