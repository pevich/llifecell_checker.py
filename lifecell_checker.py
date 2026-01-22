import os
import re
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

URL = "https://my-ambassador.lifecell.ua"

INPUT_FILE = "numbers.txt"
VALID_FILE = "valid.txt"
UNKNOWN_FILE = "unknown.txt"

# Таймаути
WAIT_LOGIN_SECONDS = 600   # 10 хв на логін + SMS
WAIT_UI_SECONDS = 30


def sanitize_numbers(lines):
    out = []
    for s in lines:
        s = s.strip()
        if not s:
            continue
        s = re.sub(r"\D+", "", s)
        if not s:
            continue
        # очікуємо 9 цифр (після 380)
        if len(s) == 9:
            out.append(s)
        else:
            # якщо юзер випадково вставив 380... -> вирізаємо 380
            if s.startswith("380") and len(s) == 12:
                out.append(s[3:])
            else:
                # залишимо як є, але потім запишемо в unknown якщо не пройде
                out.append(s)
    return out


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Lifecell LTE Checker")
        self.root.geometry("640x360")
        self.root.resizable(False, False)

        self.status_var = tk.StringVar(value="Готово. Натисни «Почати»")
        self.progress_var = tk.StringVar(value="0 / 0")

        title = ttk.Label(root, text="Lifecell LTE Checker", font=("Segoe UI", 16, "bold"))
        title.pack(pady=(12, 6))

        info = ttk.Label(
            root,
            text="Формат numbers.txt: тільки цифри ПІСЛЯ 380 (наприклад: 935180140)\n"
                 "Після запуску відкриється сайт — зайди в акаунт вручну (логін/пароль/SMS).",
            justify="center"
        )
        info.pack(pady=(0, 8))

        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=14, pady=6)

        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        ttk.Label(bar, textvariable=self.progress_var).pack(side="right")

        self.log_box = tk.Text(root, height=13, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(8, 10))
        self.log_box.configure(state="disabled")

        btns = ttk.Frame(root)
        btns.pack(pady=(0, 12))
        self.start_btn = ttk.Button(btns, text="▶ Почати", command=self.start)
        self.start_btn.pack(side="left", padx=8)

        self.stop_flag = False
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
        self.stop_flag = False
        self.start_btn.configure(state="disabled")
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    # -------- Selenium helpers --------

    def js_click(self, driver, el):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.15)
        driver.execute_script("arguments[0].click();", el)

    def wait_login(self, wait):
        # Чекаємо, поки на головній буде кнопка "Клієнт"
        return wait.until(EC.element_to_be_clickable((
            By.XPATH, "//div[contains(@class,'label') and normalize-space(text())='Клієнт']"
        )))

    def open_client(self, driver, wait):
        client = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//div[contains(@class,'label') and normalize-space(text())='Клієнт']"
        )))
        self.js_click(driver, client)
        time.sleep(0.5)

    def get_msisdn_input(self, wait):
        # інпут саме по id
        return wait.until(EC.visibility_of_element_located((By.ID, "msisdn")))

    def focus_input_infix_first(self, driver, wait):
        # ВАЖЛИВО: спочатку клік по контейнеру infix, інакше не дає вводити
        infix = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//div[contains(@class,'mat-form-field-infix')][.//input[@id='msisdn']]"
        )))
        self.js_click(driver, infix)
        time.sleep(0.2)

    def clear_after_380_and_type(self, driver, wait, number9):
        # гарантуємо що ми на формі "Клієнт" і поле існує
        self.focus_input_infix_first(driver, wait)
        field = self.get_msisdn_input(wait)

        # фокус на інпут
        self.js_click(driver, field)
        time.sleep(0.1)

        # Переходимо в кінець і чистимо все, що після 380
        field.send_keys(Keys.END)
        for _ in range(16):
            field.send_keys(Keys.BACKSPACE)
        time.sleep(0.1)

        # Вводимо 9 цифр як реальний набір (але швидко)
        # (у Angular-масок інколи краще вводити одним send_keys, але тут сайт “їсть” — робимо пачкою)
        field.send_keys(number9)
        time.sleep(0.2)

    def click_search(self, driver, wait):
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and contains(normalize-space(.),'Пошук')]]"
        )))
        self.js_click(driver, btn)

    def click_back(self, driver, wait):
        # клікаємо кнопку, яка містить mat-icon arrow_back
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//mat-icon[normalize-space(text())='arrow_back']]"
        )))
        self.js_click(driver, btn)
        time.sleep(0.8)

    def is_unknown(self, driver):
        return len(driver.find_elements(By.XPATH, "//div[contains(@class,'text') and contains(@class,'unknown') and contains(normalize-space(.),'UNKNOWN')]")) > 0

    def is_lte_no_support(self, driver):
        return len(driver.find_elements(By.XPATH, "//div[contains(@class,'header') and contains(@class,'device-no-support') and contains(normalize-space(.),'LTE')]")) > 0

    def is_lte_support(self, driver):
        return len(driver.find_elements(By.XPATH, "//div[contains(@class,'header') and contains(@class,'support') and contains(normalize-space(.),'LTE')]")) > 0

    def click_register_flow(self, driver, wait):
        # 1) Реєстрація стартового пакету
        reg = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//div[contains(@class,'label') and contains(normalize-space(.),'Реєстрація стартового пакету')]"
        )))
        self.js_click(driver, reg)

        # 2) Зареєструвати
        reg_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and contains(normalize-space(.),'Зареєструвати')]]"
        )))
        self.js_click(driver, reg_btn)

        # 3) Ок (у діалозі)
        ok_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[.//span[contains(@class,'mat-button-wrapper') and normalize-space(.)='Ок']]"
        )))
        self.js_click(driver, ok_btn)
        time.sleep(0.6)

    # -------- Main run --------

    def run(self):
        try:
            if not os.path.exists(INPUT_FILE):
                messagebox.showerror("Помилка", f"Не знайдено {INPUT_FILE} поруч з програмою.")
                self.start_btn.configure(state="normal")
                return

            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                nums = sanitize_numbers(f.readlines())

            total = len(nums)
            if total == 0:
                messagebox.showerror("Помилка", "numbers.txt порожній або без коректних номерів.")
                self.start_btn.configure(state="normal")
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
            self.log("Увійди в акаунт вручну (логін/пароль/SMS). Я сам продовжу, коли з’явиться «Клієнт».")

            # Чекаємо появу "Клієнт" після логіну
            self.wait_login(wait_login)
            self.log("Авторизацію підтверджено ✅")

            # Цикл по номерах
            for i, n in enumerate(nums, start=1):
                if self.stop_flag:
                    break

                self.set_progress(i, total)
                self.set_status(f"Перевірка: {n}")
                self.log(f"[{i}/{total}] Номер: 380{n}")

                # 1) Завжди починаємо з кнопки "Клієнт" (після back Angular може бути не на формі)
                self.open_client(driver, wait_ui)

                # 2) Фокус + ввід
                try:
                    # кілька спроб на випадок Angular-перемальовки
                    for attempt in range(3):
                        try:
                            self.clear_after_380_and_type(driver, wait_ui, n)
                            break
                        except (StaleElementReferenceException, TimeoutException):
                            time.sleep(0.4)
                            if attempt == 2:
                                raise
                except Exception:
                    self.log("  ⛔ Не вдалося знайти/ввести в поле msisdn. Пропускаю як UNKNOWN.")
                    with open(UNKNOWN_FILE, "a", encoding="utf-8") as out:
                        out.write(n + "\n")
                    continue

                # 3) Пошук
                try:
                    self.click_search(driver, wait_ui)
                except Exception:
                    self.log("  ⛔ Не натиснувся «Пошук». Пропускаю як UNKNOWN і йду назад.")
                    with open(UNKNOWN_FILE, "a", encoding="utf-8") as out:
                        out.write(n + "\n")
                    try:
                        self.click_back(driver, wait_ui)
                    except Exception:
                        pass
                    continue

                # 4) Чекаємо результат: UNKNOWN або LTE support/no-support
                result_deadline = time.time() + 20
                while time.time() < result_deadline:
                    if self.is_unknown(driver) or self.is_lte_no_support(driver) or self.is_lte_support(driver):
                        break
                    time.sleep(0.25)

                # 5) Логіка
                if self.is_unknown(driver) or self.is_lte_no_support(driver):
                    if self.is_unknown(driver):
                        self.log("  → UNKNOWN")
                    else:
                        self.log("  → LTE (не підтримує)")

                    with open(UNKNOWN_FILE, "a", encoding="utf-8") as out:
                        out.write(n + "\n")

                    # назад → наступний номер
                    try:
                        self.click_back(driver, wait_ui)
                    except Exception:
                        self.log("  ⚠ Не вдалось натиснути назад, пробую продовжити.")
                    continue

                if self.is_lte_support(driver):
                    self.log("  → LTE (підтримує) → Реєстрація…")
                    with open(VALID_FILE, "a", encoding="utf-8") as out:
                        out.write(n + "\n")

                    try:
                        self.click_register_flow(driver, wait_ui)
                        self.log("  ✅ Зареєстровано + ОК")
                    except Exception:
                        self.log("  ⚠ Не вдалася реєстрація/ОК — все одно йду назад.")
                    try:
                        self.click_back(driver, wait_ui)
                    except Exception:
                        pass
                    continue

                # Якщо не змогли визначити
                self.log("  ⚠ Не визначив статус (запишу як UNKNOWN)")
                with open(UNKNOWN_FILE, "a", encoding="utf-8") as out:
                    out.write(n + "\n")
                try:
                    self.click_back(driver, wait_ui)
                except Exception:
                    pass

            self.set_status("Готово ✅")
            self.log("Завершено. Файли: valid.txt / unknown.txt")
            try:
                driver.quit()
            except Exception:
                pass

        except Exception as e:
            messagebox.showerror("Помилка", str(e))
        finally:
            self.start_btn.configure(state="normal")


if __name__ == "__main__":
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()
