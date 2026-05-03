import json
import os
import sys
import sqlite3
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from auth import login
from tg1600 import TG1600Client

CONFIG_FILE = "local_config.json"
SESSION_FILE = "session.json"
DB_FILE = "nuxsms_local.db"
SESSION_MAX_HOURS = 24


# 🔥 IMPORTANTE para PyInstaller
def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def save_session(data):
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f)


def load_session():
    if not os.path.exists(SESSION_FILE):
        return None
    with open(SESSION_FILE, "r") as f:
        return json.load(f)


def clear_session():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)


def session_is_valid(session):
    if not session:
        return False
    login_time = session.get("login_time")
    if not login_time:
        return False

    return (time.time() - login_time) < (SESSION_MAX_HOURS * 3600)


def session_remaining(session):
    if not session:
        return "0h"

    remaining = (SESSION_MAX_HOURS * 3600) - (time.time() - session["login_time"])
    if remaining <= 0:
        return "expirada"

    h = int(remaining // 3600)
    m = int((remaining % 3600) // 60)
    return f"{h}h {m}m"


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("NuxSMS Local")
        self.root.geometry("950x720")
        self.root.configure(bg="#0b1020")

        self.authenticated = False
        self.session = None

        self.build_ui()
        self.restore_session()

    # ---------------- UI ----------------

    def build_ui(self):
        header = tk.Frame(self.root, bg="#0b1020")
        header.pack(fill="x", padx=20, pady=15)

        # LOGO
        logo_path = resource_path("logo.png")
        self.logo_img = None

        if os.path.exists(logo_path):
            try:
                img = Image.open(logo_path)
                img = img.resize((100, 100), Image.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(img)

                box = tk.Frame(header, bg="#ffffff", padx=6, pady=6)
                box.pack(side="left", padx=(0, 15))

                tk.Label(box, image=self.logo_img, bg="#ffffff").pack()
            except:
                pass

        # TITULO
        text_box = tk.Frame(header, bg="#0b1020")
        text_box.pack(side="left")

        tk.Label(
            text_box,
            text="NUXSMS LOCAL",
            font=("Arial", 26, "bold"),
            fg="#f8fafc",
            bg="#0b1020"
        ).pack(anchor="w")

        tk.Label(
            text_box,
            text="Acceso local + TG Series Gateway",
            font=("Arial", 12),
            fg="#cbd5e1",
            bg="#0b1020"
        ).pack(anchor="w")

        # STATUS
        self.status = tk.Label(
            self.root,
            text="Estado: no autenticado",
            fg="#ef4444",
            bg="#0b1020",
            font=("Arial", 12, "bold")
        )
        self.status.pack(pady=5)

        # TABS
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=10)

        self.tab_login = tk.Frame(self.tabs, bg="#111827")
        self.tab_cfg = tk.Frame(self.tabs, bg="#111827")

        self.tabs.add(self.tab_login, text="Login")
        self.tabs.add(self.tab_cfg, text="Configuración")

        self.build_login_tab()
        self.lock_tabs()

        self.root.after(60000, self.check_session)

    def build_login_tab(self):
        tk.Label(
            self.tab_login,
            text="Acceso al sistema",
            font=("Arial", 22, "bold"),
            fg="#f8fafc",
            bg="#111827"
        ).pack(pady=40)

        tk.Button(
            self.tab_login,
            text="Iniciar sesión",
            command=self.do_login,
            bg="#f59e0b",
            fg="#111827",
            font=("Arial", 12, "bold"),
            padx=20,
            pady=8
        ).pack(pady=10)

        tk.Button(
            self.tab_login,
            text="Cerrar sesión local",
            command=self.do_logout,
            bg="#2563eb",
            fg="white"
        ).pack(pady=5)

    # ---------------- AUTH ----------------

    def do_login(self):
        try:
            result = login()

            self.session = {
                "login_time": result["login_time"],
                "claims": result["claims"]
            }

            save_session(self.session)

            email = result["claims"].get("email", "usuario")

            self.status.config(
                text=f"Autenticado: {email} | {session_remaining(self.session)}",
                fg="#22c55e"
            )

            self.authenticated = True
            self.lock_tabs()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def do_logout(self):
        clear_session()
        self.authenticated = False
        self.session = None

        self.status.config(
            text="Estado: no autenticado",
            fg="#ef4444"
        )

        self.lock_tabs()

    def restore_session(self):
        session = load_session()

        if session and session_is_valid(session):
            self.session = session
            self.authenticated = True

            email = session["claims"].get("email", "usuario")

            self.status.config(
                text=f"Autenticado: {email} | {session_remaining(session)}",
                fg="#22c55e"
            )

            self.lock_tabs()

    def check_session(self):
        if self.authenticated:
            if not session_is_valid(self.session):
                self.do_logout()
                messagebox.showwarning("Sesión expirada", "Debes iniciar sesión nuevamente")

        self.root.after(60000, self.check_session)

    def lock_tabs(self):
        if self.authenticated:
            self.tabs.tab(1, state="normal")
        else:
            self.tabs.tab(1, state="disabled")


# ---------------- RUN ----------------

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
