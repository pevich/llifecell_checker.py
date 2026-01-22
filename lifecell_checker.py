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
WAIT_UI_SECONDS = 8
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
            # підтримка і 9 цифр, і 380XXXXXXXXX
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
        self.root.geometry("760x460")

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

        self.log_box = tk.Text(root, height=14)
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
        # якщо кнопка "Клієнт" є — натиснемо, якщо нема — працюємо як є
        try:
            client = WebDriverWait(driver, 1.5, poll_frequency=POLL).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'label') and normalize-space(.)='Клієнт']"))
            )
            self.js_click(driver, client)
        except Exception:
            pass

        wait.until(EC.presence_of_element_located((By.ID, "msisdn")))

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
        # ✅ ФІКС: клікаємо по КНОПЦІ, а не по span (в mat-button-wrapper можуть бути пробіли)
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Пошук']]"
        )))
        self.js_click(driver, btn)

    def has_services(self, driver):
        return len(driver.find_elements(By.XPATH, "//div[contains(@class,'label') and normalize-space(.)='Реєстрація послуг']")) > 0

    def register_start_pack(self, driver):
        self.js_click(driver, driver.find_element(
            By.XPATH, "//div[contains(@class,'label') and contains(normalize-space(.),'Реєстрація стартового пакету')]"
        ))
        self.js_click(driver, driver.find_element(
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Зареєструвати']]"
        ))
        self.js_click(driver, driver.find_element(
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Ок']]"
        ))

    def back(self, driver, wait):
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//mat-icon[normalize-space(text())='arrow_back']]"
        )))
        self.js_click(driver, btn)

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
                    self.ensure_client(driver, wait)
                    self.set_number(driver, wait, number)
                    self.click_search(driver, wait)

                    # чекаємо трохи на появу "Реєстрація послуг"
                    try:
                        WebDriverWait(driver, 4, poll_frequency=POLL).until(lambda d: self.has_services(d))
                        # є "Реєстрація послуг" → робимо реєстрацію стартового пакету
                        self.register_start_pack(driver)

                        with open(VALID_FILE, "a", encoding="utf-8") as f:
                            f.write(number + "\n")

                        # ✅ ТІЛЬКИ ЗАРЕЄСТРОВАНІ видаляємо з numbers.txt (тобто НЕ додаємо в remaining)
                        self.log("  ✔ Зареєстровано → VALID (видалено з numbers.txt)")
                        continue

                    except Exception:
                        # немає "Реєстрація послуг" → TRASH + назад, але номер лишається в numbers.txt
                        with open(TRASH_FILE, "a", encoding="utf-8") as f:
                            f.write(number + "\n")
                        self.log("  🗑 Нема «Реєстрація послуг» → TRASH (залишив у numbers.txt)")
                        try:
                            self.back(driver, wait)
                        except Exception:
                            pass

                        remaining.append(number)
                        continue

                except Exception:
                    # якщо десь зламалось на номері — теж залишимо в numbers.txt
                    with open(TRASH_FILE, "a", encoding="utf-8") as f:
                        f.write(number + "\n")
                    self.log("  🗑 Помилка на номері → TRASH (залишив у numbers.txt)")
                    remaining.append(number)
                    try:
                        self.back(driver, wait)
                    except Exception:
                        pass
                    continue

            # оновлюємо numbers.txt: лишаються тільки НЕзареєстровані
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
