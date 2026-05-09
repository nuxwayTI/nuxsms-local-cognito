import json
import os
import sys
import sqlite3
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd
from PIL import Image, ImageTk
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from auth import login
from tg1600 import TG1600Client

CONFIG_FILE = "local_config.json"
SESSION_FILE = "session.json"
DB_FILE = "nuxsms_local.db"
COUNTRY_CODE = "591"
SESSION_MAX_HOURS = 24
# Para pruebas puedes cambiar a 120 segundos.
# Para produccion usa: SESSION_TEST_SECONDS = None
SESSION_TEST_SECONDS = 120


def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def default_config():
    return {
        "agent_id": "tg1600-001",
        "tg_host": "192.168.20.31",
        "tg_port": 5038,
        "tg_user": "apiuser",
        "tg_pass": "apipass",
        "poll_seconds": 1.0,
    }


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return default_config()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def save_session(data):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_session():
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clear_session():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)


def session_is_valid(session):
    if not session:
        return False
    login_time = session.get("login_time")
    if not login_time:
        return False
    max_seconds = SESSION_TEST_SECONDS if SESSION_TEST_SECONDS is not None else (SESSION_MAX_HOURS * 3600)
    return (time.time() - float(login_time)) < max_seconds


def session_remaining_text(session):
    if not session or not session.get("login_time"):
        return "0h"
    max_seconds = SESSION_TEST_SECONDS if SESSION_TEST_SECONDS is not None else (SESSION_MAX_HOURS * 3600)
    remaining = max_seconds - (time.time() - float(session["login_time"]))
    if remaining <= 0:
        return "expirada"
    h = int(remaining // 3600)
    m = int((remaining % 3600) // 60)
    s = int(remaining % 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def normalize_phone(phone):
    phone = str(phone).strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.endswith(".0"):
        phone = phone[:-2]
    if phone.startswith("+"):
        return phone
    if phone.startswith(COUNTRY_CODE):
        return "+" + phone
    return "+" + COUNTRY_CODE + phone


def parse_chips(chips_raw):
    chips = []
    for item in chips_raw.split(","):
        item = item.strip()
        if item:
            chip = int(item)
            if chip < 1 or chip > 32:
                raise ValueError("Chip fuera de rango.")
            chips.append(chip)
    if not chips:
        raise ValueError("Debes ingresar al menos un chip.")
    return chips


def safe_filename(text):
    cleaned = "".join(c for c in str(text) if c.isalnum() or c in (" ", "_", "-")).strip()
    cleaned = cleaned.replace(" ", "_")
    if not cleaned:
        cleaned = "campana"
    return cleaned[:60]


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        message TEXT NOT NULL,
        chips TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        phone TEXT NOT NULL,
        text TEXT NOT NULL,
        chip INTEGER NOT NULL,
        status TEXT NOT NULL,
        result TEXT,
        created_at TEXT NOT NULL,
        sent_at TEXT
    )
    """)

    conn.commit()
    conn.close()


class App:
    def __init__(self, root):
        init_db()

        self.root = root
        self.root.title("NuxSMS Local")
        self.root.geometry("1120x780")
        self.root.configure(bg="#0b1020")

        self.authenticated = False
        self.user_email = None
        self.session = None
        self.cfg = load_config()
        self.running = False
        self.worker = None
        self.logo_img = None

        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.try_restore_session()

    def setup_ui(self):
        header = tk.Frame(self.root, bg="#0b1020")
        header.pack(fill="x", padx=20, pady=15)

        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
            try:
                img = Image.open(logo_path)
                img = img.resize((100, 100), Image.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(img)
                logo_box = tk.Frame(header, bg="#ffffff", padx=6, pady=6)
                logo_box.pack(side="left", padx=(0, 18))
                tk.Label(logo_box, image=self.logo_img, bg="#ffffff").pack()
            except Exception:
                pass

        title_box = tk.Frame(header, bg="#0b1020")
        title_box.pack(side="left")

        tk.Label(
            title_box,
            text="NUXSMS LOCAL",
            font=("Arial", 26, "bold"),
            fg="#f8fafc",
            bg="#0b1020",
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="Acceso local + TG Series Gateway",
            font=("Arial", 12),
            fg="#cbd5e1",
            bg="#0b1020",
        ).pack(anchor="w")

        self.status = tk.Label(
            self.root,
            text="Estado: no autenticado",
            fg="#ef4444",
            bg="#0b1020",
            font=("Arial", 12, "bold"),
        )
        self.status.pack(pady=4)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=12)

        self.tab_login = tk.Frame(self.notebook, bg="#111827")
        self.tab_config = tk.Frame(self.notebook, bg="#111827")
        self.tab_campaign = tk.Frame(self.notebook, bg="#111827")
        self.tab_single = tk.Frame(self.notebook, bg="#111827")
        self.tab_history = tk.Frame(self.notebook, bg="#111827")
        self.tab_help = tk.Frame(self.notebook, bg="#111827")

        self.notebook.add(self.tab_login, text="Login")
        self.notebook.add(self.tab_config, text="Configuración TG")
        self.notebook.add(self.tab_campaign, text="Lanzador SMS")
        self.notebook.add(self.tab_single, text="SMS individual")
        self.notebook.add(self.tab_history, text="Historial")
        self.notebook.add(self.tab_help, text="Manual / Ayuda")

        self.build_login_tab()
        self.build_config_tab()
        self.build_campaign_tab()
        self.build_single_sms_tab()
        self.build_history_tab()
        self.build_help_tab()

        self.lock_tabs()
        self.root.after(1000 if SESSION_TEST_SECONDS is not None else 60000, self.check_session_timer)

    def lock_tabs(self):
        state = "normal" if self.authenticated else "disabled"
        self.notebook.tab(1, state=state)
        self.notebook.tab(2, state=state)
        self.notebook.tab(3, state=state)
        self.notebook.tab(4, state=state)
        self.notebook.tab(5, state=state)

    def build_login_tab(self):
        tk.Label(
            self.tab_login,
            text="Acceso al sistema",
            font=("Arial", 22, "bold"),
            fg="#f8fafc",
            bg="#111827",
        ).pack(pady=32)

        tk.Button(
            self.tab_login,
            text="Iniciar sesión",
            command=self.do_login,
            bg="#f59e0b",
            fg="#111827",
            font=("Arial", 12, "bold"),
            padx=20,
            pady=8,
        ).pack(pady=8)

        tk.Button(
            self.tab_login,
            text="Cerrar sesión local",
            command=self.do_logout,
            bg="#2563eb",
            fg="white",
            font=("Arial", 11, "bold"),
            padx=18,
            pady=7,
        ).pack(pady=5)

        self.login_output = tk.Text(
            self.tab_login,
            height=12,
            width=110,
            bg="#030712",
            fg="#e5e7eb",
        )
        self.login_output.pack(pady=20)

    def build_config_tab(self):
        form = tk.Frame(self.tab_config, bg="#111827", padx=20, pady=20)
        form.pack(anchor="nw", fill="x")

        self.entries = {}
        fields = [
            ("agent_id", "Agent ID"),
            ("tg_host", "IP TG"),
            ("tg_port", "Puerto TG"),
            ("tg_user", "Usuario TG"),
            ("tg_pass", "Password TG"),
            ("poll_seconds", "Poll segundos"),
        ]

        for row, (key, label) in enumerate(fields):
            tk.Label(
                form,
                text=label,
                fg="#e5e7eb",
                bg="#111827",
                font=("Arial", 10, "bold"),
            ).grid(row=row, column=0, sticky="w", pady=6)

            entry = tk.Entry(
                form,
                width=58,
                show="*" if key == "tg_pass" else "",
                bg="#0c1220",
                fg="#f8fafc",
                insertbackground="#f8fafc",
            )
            entry.insert(0, str(self.cfg.get(key, "")))
            entry.grid(row=row, column=1, padx=12, pady=6)
            self.entries[key] = entry

        tk.Button(
            form,
            text="Guardar configuración",
            command=self.save_tg_config,
            bg="#f59e0b",
            fg="#111827",
            font=("Arial", 10, "bold"),
        ).grid(row=len(fields), column=1, sticky="w", pady=12)

        tk.Button(
            form,
            text="Probar conexión TG",
            command=self.test_tg_connection,
            bg="#2563eb",
            fg="white",
            font=("Arial", 10, "bold"),
        ).grid(row=len(fields), column=1, sticky="e", pady=12)

    def build_campaign_tab(self):
        top = tk.Frame(self.tab_campaign, bg="#111827", padx=20, pady=20)
        top.pack(fill="x")

        tk.Label(top, text="Nombre campaña", fg="#e5e7eb", bg="#111827").grid(row=0, column=0, sticky="w")
        self.campaign_name = tk.Entry(top, width=58, bg="#0c1220", fg="#f8fafc")
        self.campaign_name.grid(row=0, column=1, padx=10, pady=5)

        tk.Label(top, text="Mensaje", fg="#e5e7eb", bg="#111827").grid(row=1, column=0, sticky="w")
        self.message_text = tk.Text(top, width=58, height=4, bg="#0c1220", fg="#f8fafc")
        self.message_text.grid(row=1, column=1, padx=10, pady=5)

        tk.Label(top, text="Chips. Ej: 2,3,4", fg="#e5e7eb", bg="#111827").grid(row=2, column=0, sticky="w")
        self.chips_entry = tk.Entry(top, width=58, bg="#0c1220", fg="#f8fafc")
        self.chips_entry.insert(0, "2")
        self.chips_entry.grid(row=2, column=1, padx=10, pady=5)

        self.file_path = tk.StringVar()

        tk.Button(
            top,
            text="Seleccionar Excel/CSV",
            command=self.select_file,
            bg="#2563eb",
            fg="white",
        ).grid(row=3, column=0, pady=8)

        tk.Label(
            top,
            textvariable=self.file_path,
            fg="#cbd5e1",
            bg="#111827",
        ).grid(row=3, column=1, sticky="w")

        tk.Button(
            top,
            text="Crear campaña local",
            command=self.create_campaign,
            bg="#f59e0b",
            fg="#111827",
        ).grid(row=4, column=0, pady=10)

        tk.Button(
            top,
            text="Iniciar envío",
            command=self.start_sending,
            bg="#22c55e",
            fg="#111827",
        ).grid(row=4, column=1, sticky="w", pady=10)

        tk.Button(
            top,
            text="Pausar envío",
            command=self.stop_sending,
            bg="#ef4444",
            fg="white",
        ).grid(row=4, column=1, sticky="e", pady=10)

        self.send_log = tk.Text(
            self.tab_campaign,
            height=16,
            width=125,
            bg="#030712",
            fg="#e5e7eb",
        )
        self.send_log.pack(padx=20, pady=10)

    def build_single_sms_tab(self):
        top = tk.Frame(self.tab_single, bg="#111827", padx=20, pady=20)
        top.pack(fill="x", anchor="nw")

        tk.Label(
            top,
            text="Enviar SMS individual",
            font=("Arial", 20, "bold"),
            fg="#f8fafc",
            bg="#111827",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))

        tk.Label(top, text="Número", fg="#e5e7eb", bg="#111827").grid(row=1, column=0, sticky="w")
        self.single_phone = tk.Entry(top, width=58, bg="#0c1220", fg="#f8fafc")
        self.single_phone.grid(row=1, column=1, padx=10, pady=5, sticky="w")

        tk.Label(top, text="Mensaje", fg="#e5e7eb", bg="#111827").grid(row=2, column=0, sticky="nw")
        self.single_message = tk.Text(top, width=58, height=5, bg="#0c1220", fg="#f8fafc")
        self.single_message.grid(row=2, column=1, padx=10, pady=5, sticky="w")

        tk.Label(top, text="Chip", fg="#e5e7eb", bg="#111827").grid(row=3, column=0, sticky="w")
        self.single_chip = tk.Entry(top, width=58, bg="#0c1220", fg="#f8fafc")
        self.single_chip.insert(0, "2")
        self.single_chip.grid(row=3, column=1, padx=10, pady=5, sticky="w")

        tk.Button(
            top,
            text="Enviar SMS ahora",
            command=self.send_single_sms,
            bg="#22c55e",
            fg="#111827",
            font=("Arial", 10, "bold"),
        ).grid(row=4, column=1, sticky="w", padx=10, pady=12)

        self.single_log = tk.Text(
            self.tab_single,
            height=14,
            width=125,
            bg="#030712",
            fg="#e5e7eb",
        )
        self.single_log.pack(padx=20, pady=10)

    def build_help_tab(self):
        help_text = """NUXSMS LOCAL - MANUAL RÁPIDO

1. Login
- Inicia sesión con el usuario autorizado por Nuxway Technology.
- La sesión local dura 24 horas.

2. Configuración TG
- Coloca IP, puerto, usuario y password del gateway TG1600.
- Usa Probar conexión TG antes de enviar.

3. Lanzador SMS por Excel/CSV
- El archivo debe tener los teléfonos en la primera columna.
- Completa nombre de campaña, mensaje y chips. Ejemplo: 2,3,4.
- El sistema reparte los SMS en round-robin entre los chips indicados.
- Si un envío falla, se reintenta automáticamente una sola vez.

4. SMS individual
- Ingresa número, mensaje y chip.
- El sistema normaliza números bolivianos agregando +591 si corresponde.
- Si falla el primer intento, reintenta una sola vez.

5. Historial
- Muestra campañas, enviados, fallidos y pendientes.
- Puedes ver el detalle de una campaña o exportarla a Excel.

Recomendación
- No abras el Excel exportado mientras generas otro reporte.
- Si el gateway no responde, revisa red, credenciales y chip activo."""

        tk.Label(
            self.tab_help,
            text="Manual / Ayuda",
            font=("Arial", 22, "bold"),
            fg="#f8fafc",
            bg="#111827",
        ).pack(anchor="w", padx=20, pady=(24, 8))

        box = tk.Text(
            self.tab_help,
            height=28,
            width=120,
            bg="#030712",
            fg="#e5e7eb",
            wrap="word",
        )
        box.pack(fill="both", expand=True, padx=20, pady=12)
        box.insert(tk.END, help_text)
        box.config(state="disabled")

    def send_single_sms(self):
        if not session_is_valid(self.session):
            messagebox.showwarning("Sesión expirada", "Debes iniciar sesión antes de enviar.")
            return

        try:
            self.save_tg_config()
            phone = normalize_phone(self.single_phone.get())
            message = self.single_message.get("1.0", tk.END).strip()
            chip = int(self.single_chip.get().strip())

            if not phone or not message:
                raise Exception("Completa número y mensaje.")
            if chip < 1 or chip > 32:
                raise Exception("Chip fuera de rango. Usa 1 a 32.")

            thread = threading.Thread(
                target=self.send_single_sms_worker,
                args=(phone, message, chip),
                daemon=True,
            )
            thread.start()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def log_single(self, text):
        self.single_log.insert(tk.END, text + "\n")
        self.single_log.see(tk.END)

    def send_sms_with_one_retry(self, tg, chip, phone, text, message_id):
        first = tg.send_sms(chip=chip, to_number=phone, message=text, message_id=message_id)
        if first.get("success"):
            first["attempts"] = 1
            return first

        time.sleep(1)
        second = tg.send_sms(chip=chip, to_number=phone, message=text, message_id=f"{message_id}_retry")
        second["attempts"] = 2
        second["first_raw"] = first.get("raw", "")
        return second

    def send_single_sms_worker(self, phone, message, chip):
        tg = None
        try:
            self.root.after(0, self.log_single, f"Conectando al TG para enviar a {phone} por chip {chip}...")
            tg = TG1600Client(
                host=self.cfg["tg_host"],
                port=self.cfg["tg_port"],
                username=self.cfg["tg_user"],
                password=self.cfg["tg_pass"],
            )
            tg.connect()
            result = self.send_sms_with_one_retry(tg, chip, phone, message, f"single_{int(time.time())}")
            status = "ENVIADO" if result.get("success") else "FALLIDO"
            self.root.after(
                0,
                self.log_single,
                f"Resultado: {status} | intentos: {result.get('attempts', 1)} | chip {result.get('real_chip', chip)}",
            )
            self.root.after(0, self.log_single, (result.get("raw") or "")[:1200])
        except Exception as e:
            self.root.after(0, self.log_single, "ERROR: " + str(e))
        finally:
            if tg:
                try:
                    tg.close()
                except Exception:
                    pass

    def build_history_tab(self):
        top = tk.Frame(self.tab_history, bg="#111827", padx=15, pady=15)
        top.pack(fill="x")

        tk.Button(
            top,
            text="Actualizar historial",
            command=self.load_history,
            bg="#2563eb",
            fg="white",
        ).pack(side="left", padx=5)

        tk.Button(
            top,
            text="Ver campaña",
            command=self.view_selected_campaign,
            bg="#22c55e",
            fg="#111827",
        ).pack(side="left", padx=5)

        tk.Button(
            top,
            text="Exportar campaña Excel",
            command=self.export_selected_campaign,
            bg="#f59e0b",
            fg="#111827",
        ).pack(side="left", padx=5)

        tk.Button(
            top,
            text="Eliminar campaña",
            command=self.delete_selected_campaign,
            bg="#ef4444",
            fg="white",
        ).pack(side="left", padx=5)

        tk.Button(
            top,
            text="Eliminar todo",
            command=self.delete_all_history,
            bg="#991b1b",
            fg="white",
        ).pack(side="left", padx=5)

        columns = ("id", "name", "chips", "total", "queued", "processing", "sent", "failed", "created")
        self.history_tree = ttk.Treeview(self.tab_history, columns=columns, show="headings", height=18)

        headers = {
            "id": "ID",
            "name": "Nombre",
            "chips": "Chips",
            "total": "Total",
            "queued": "Cola",
            "processing": "Procesando",
            "sent": "Enviados",
            "failed": "Fallidos",
            "created": "Fecha",
        }

        widths = {
            "id": 55,
            "name": 160,
            "chips": 90,
            "total": 70,
            "queued": 70,
            "processing": 95,
            "sent": 85,
            "failed": 85,
            "created": 180,
        }

        for col in columns:
            self.history_tree.heading(col, text=headers[col])
            self.history_tree.column(col, width=widths[col], anchor="center")

        self.history_tree.pack(fill="both", expand=True, padx=15, pady=10)
        self.history_tree.bind("<Double-1>", lambda event: self.view_selected_campaign())

        self.load_history()

    def log_login(self, text):
        self.login_output.insert(tk.END, text + "\n")
        self.login_output.see(tk.END)

    def log_send(self, text):
        self.send_log.insert(tk.END, text + "\n")
        self.send_log.see(tk.END)

    def try_restore_session(self):
        session = load_session()
        if session_is_valid(session):
            claims = session.get("claims", {})
            self.user_email = claims.get("email", "usuario")
            self.session = session
            self.authenticated = True
            self.status.config(
                text=f"Autenticado: {self.user_email} | {session_remaining_text(session)}",
                fg="#22c55e",
            )
            self.log_login(f"Sesión restaurada: {self.user_email}")
            self.lock_tabs()
        else:
            clear_session()
            self.authenticated = False
            self.lock_tabs()

    def do_login(self):
        try:
            self.log_login("Abriendo acceso al sistema...")
            result = login()
            claims = result.get("claims", {})
            self.user_email = claims.get("email", "usuario")
            self.authenticated = True

            session = {
                "claims": claims,
                "tokens": result.get("tokens", {}),
                "login_time": result.get("login_time", time.time()),
            }

            save_session(session)
            self.session = session

            self.status.config(
                text=f"Autenticado: {self.user_email} | {session_remaining_text(session)}",
                fg="#22c55e",
            )
            self.log_login(f"LOGIN OK: {self.user_email}")
            self.lock_tabs()
            self.notebook.select(self.tab_config)

        except Exception as e:
            self.status.config(text="Error de autenticación", fg="#ef4444")
            self.log_login("ERROR: " + str(e))
            messagebox.showerror("Error", str(e))

    def logout_local(self):
        clear_session()
        self.authenticated = False
        self.user_email = None
        self.session = None
        self.running = False
        self.status.config(text="Estado: no autenticado", fg="#ef4444")
        self.lock_tabs()
        self.notebook.select(self.tab_login)

    def do_logout(self):
        self.logout_local()
        self.log_login("Sesión local cerrada.")

    def on_close(self):
        if self.authenticated:
            confirm = messagebox.askyesno(
                "Cerrar NUXSMS",
                "¿Quieres salir de NUXSMS?\n\nSe cerrará la sesión local y tendrás que iniciar sesión nuevamente al abrir el sistema.",
            )
            if not confirm:
                return
            self.logout_local()
        else:
            confirm = messagebox.askyesno("Cerrar NUXSMS", "¿Quieres salir de NUXSMS?")
            if not confirm:
                return
        self.root.destroy()

    def check_session_timer(self):
        if self.authenticated:
            if not session_is_valid(self.session):
                self.running = False
                clear_session()
                self.authenticated = False
                self.status.config(text="Sesión expirada. Inicia sesión otra vez.", fg="#ef4444")
                self.lock_tabs()
                self.notebook.select(self.tab_login)
                msg = "La sesión expiró. Debes iniciar sesión nuevamente."
                if SESSION_TEST_SECONDS is None:
                    msg = "Han pasado 24 horas. Debes iniciar sesión nuevamente."
                messagebox.showwarning("Sesión expirada", msg)
            else:
                self.status.config(
                    text=f"Autenticado: {self.user_email} | {session_remaining_text(self.session)}",
                    fg="#22c55e",
                )
        self.root.after(1000 if SESSION_TEST_SECONDS is not None else 60000, self.check_session_timer)

    def save_tg_config(self):
        cfg = {}
        for key, entry in self.entries.items():
            value = entry.get().strip()
            if key == "tg_port":
                value = int(value)
            if key == "poll_seconds":
                value = float(value)
            cfg[key] = value

        save_config(cfg)
        self.cfg = cfg
        messagebox.showinfo("OK", "Configuración guardada")

    def test_tg_connection(self):
        try:
            self.save_tg_config()
            tg = TG1600Client(
                host=self.cfg["tg_host"],
                port=self.cfg["tg_port"],
                username=self.cfg["tg_user"],
                password=self.cfg["tg_pass"],
            )
            tg.connect()
            tg.close()
            messagebox.showinfo("OK", "TG conectado correctamente")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def select_file(self):
        path = filedialog.askopenfilename(filetypes=[("Excel/CSV", "*.xlsx *.csv")])
        if path:
            self.file_path.set(path)

    def read_phones(self, path):
        if path.lower().endswith(".csv"):
            df = pd.read_csv(path)
        else:
            df = pd.read_excel(path)

        first_col = df.columns[0]
        phones = []
        for value in df[first_col].dropna().tolist():
            phones.append(normalize_phone(value))
        return phones

    def create_campaign(self):
        try:
            name = self.campaign_name.get().strip()
            message = self.message_text.get("1.0", tk.END).strip()
            chips_raw = self.chips_entry.get().strip()
            path = self.file_path.get()

            if not name or not message or not chips_raw or not path:
                raise Exception("Completa campaña, mensaje, chips y archivo.")

            chips = parse_chips(chips_raw)
            phones = self.read_phones(path)

            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()

            created_at = time.strftime("%Y-%m-%d %H:%M:%S")

            cur.execute(
                "INSERT INTO campaigns (name, message, chips, created_at) VALUES (?, ?, ?, ?)",
                (name, message, ",".join(str(c) for c in chips), created_at),
            )
            campaign_id = cur.lastrowid

            for index, phone in enumerate(phones):
                chip = chips[index % len(chips)]
                cur.execute(
                    """
                    INSERT INTO messages
                    (campaign_id, phone, text, chip, status, result, created_at, sent_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (campaign_id, phone, message, chip, "queued", None, created_at, None),
                )

            conn.commit()
            conn.close()

            self.log_send(f"Campaña creada ID {campaign_id} con {len(phones)} contactos.")
            self.log_send(f"Round robin chips: {','.join(str(c) for c in chips)}")
            self.load_history()
            self.notebook.select(self.tab_history)

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def start_sending(self):
        if self.running:
            messagebox.showinfo("Info", "Ya está enviando.")
            return

        if not session_is_valid(self.session):
            self.running = False
            clear_session()
            self.authenticated = False
            self.lock_tabs()
            messagebox.showwarning("Sesión expirada", "Debes iniciar sesión antes de enviar.")
            return

        self.save_tg_config()
        self.running = True
        self.worker = threading.Thread(target=self.send_loop, daemon=True)
        self.worker.start()

    def stop_sending(self):
        self.running = False
        self.log_send("Pausa solicitada. Se detendrá después del SMS actual.")

    def send_loop(self):
        tg = None
        try:
            self.log_send("Conectando al TG...")
            tg = TG1600Client(
                host=self.cfg["tg_host"],
                port=self.cfg["tg_port"],
                username=self.cfg["tg_user"],
                password=self.cfg["tg_pass"],
            )
            tg.connect()
            self.log_send("TG conectado correctamente.")

            poll_seconds = float(self.cfg["poll_seconds"])

            while self.running:
                if not session_is_valid(self.session):
                    self.running = False
                    clear_session()
                    self.authenticated = False
                    self.root.after(0, self.lock_tabs)
                    self.log_send("Sesión expirada. Envío detenido.")
                    break

                conn = sqlite3.connect(DB_FILE)
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, phone, text, chip
                    FROM messages
                    WHERE status='queued'
                    ORDER BY id ASC
                    LIMIT 1
                """)
                row = cur.fetchone()

                if not row:
                    conn.close()
                    self.log_send("No hay más mensajes en cola.")
                    self.running = False
                    break

                msg_id, phone, text, chip = row

                cur.execute("UPDATE messages SET status='processing' WHERE id=?", (msg_id,))
                conn.commit()
                conn.close()

                self.root.after(0, self.load_history)
                self.log_send(f"Enviando ID {msg_id} a {phone} por chip {chip}")

                result = self.send_sms_with_one_retry(
                    tg=tg,
                    chip=chip,
                    phone=phone,
                    text=text,
                    message_id=msg_id,
                )

                status = "sent" if result["success"] else "failed"
                sent_at = time.strftime("%Y-%m-%d %H:%M:%S")

                conn = sqlite3.connect(DB_FILE)
                cur = conn.cursor()
                cur.execute("""
                    UPDATE messages
                    SET status=?, result=?, sent_at=?
                    WHERE id=?
                """, (status, result["raw"][:3000], sent_at, msg_id))
                conn.commit()
                conn.close()

                self.log_send(
                    f"Resultado ID {msg_id}: {status} | intentos {result.get('attempts', 1)} | chip web {result['requested_chip']} | TG {result['real_chip']}"
                )
                self.root.after(0, self.load_history)

                time.sleep(poll_seconds)

            if tg:
                tg.close()

        except Exception as e:
            self.running = False
            if tg:
                try:
                    tg.close()
                except Exception:
                    pass
            self.log_send("ERROR: " + str(e))

    def load_history(self):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()

        cur.execute("""
        SELECT c.id, c.name, c.chips, c.created_at,
               COUNT(m.id) AS total,
               SUM(CASE WHEN m.status='queued' THEN 1 ELSE 0 END) AS queued,
               SUM(CASE WHEN m.status='processing' THEN 1 ELSE 0 END) AS processing,
               SUM(CASE WHEN m.status='sent' THEN 1 ELSE 0 END) AS sent,
               SUM(CASE WHEN m.status='failed' THEN 1 ELSE 0 END) AS failed
        FROM campaigns c
        LEFT JOIN messages m ON m.campaign_id = c.id
        GROUP BY c.id
        ORDER BY c.id DESC
        """)
        rows = cur.fetchall()
        conn.close()

        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        for r in rows:
            self.history_tree.insert("", "end", values=(
                r[0],
                r[1],
                r[2],
                r[4] or 0,
                r[5] or 0,
                r[6] or 0,
                r[7] or 0,
                r[8] or 0,
                r[3],
            ))

    def get_selected_campaign_id(self):
        selected = self.history_tree.selection()
        if not selected:
            messagebox.showwarning("Selecciona campaña", "Selecciona una campaña primero.")
            return None
        values = self.history_tree.item(selected[0], "values")
        return int(values[0])

    def get_campaign_data(self, campaign_id):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()

        cur.execute("SELECT id, name, message, chips, created_at FROM campaigns WHERE id=?", (campaign_id,))
        campaign = cur.fetchone()

        cur.execute("""
        SELECT id, phone, chip, status, created_at, sent_at, result
        FROM messages
        WHERE campaign_id=?
        ORDER BY id ASC
        """, (campaign_id,))
        messages = cur.fetchall()

        conn.close()
        return campaign, messages

    def view_selected_campaign(self):
        campaign_id = self.get_selected_campaign_id()
        if not campaign_id:
            return

        campaign, messages = self.get_campaign_data(campaign_id)

        if not campaign:
            messagebox.showerror("Error", "Campaña no encontrada.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Resultados campaña {campaign_id}")
        win.geometry("1120x680")
        win.configure(bg="#0b1020")

        header = tk.Frame(win, bg="#0b1020")
        header.pack(fill="x", padx=15, pady=12)

        tk.Label(header, text=campaign[1], font=("Arial", 20, "bold"),
                 fg="#f8fafc", bg="#0b1020").pack(anchor="w")

        tk.Label(header, text=f"Chips: {campaign[3]} | Fecha: {campaign[4]}",
                 fg="#cbd5e1", bg="#0b1020").pack(anchor="w")

        tk.Label(header, text=f"Mensaje: {campaign[2]}",
                 fg="#cbd5e1", bg="#0b1020").pack(anchor="w", pady=(0, 8))

        tk.Button(
            header,
            text="Exportar Excel",
            command=lambda: self.export_campaign_by_id(campaign_id),
            bg="#f59e0b",
            fg="#111827",
        ).pack(anchor="w", pady=5)

        columns = ("id", "phone", "chip", "status", "created", "sent", "result")
        tree = ttk.Treeview(win, columns=columns, show="headings", height=22)

        headers = {
            "id": "ID",
            "phone": "Teléfono",
            "chip": "Chip",
            "status": "Estado",
            "created": "Creado",
            "sent": "Enviado",
            "result": "Respuesta TG",
        }

        widths = {
            "id": 55,
            "phone": 150,
            "chip": 70,
            "status": 90,
            "created": 160,
            "sent": 160,
            "result": 450,
        }

        for col in columns:
            tree.heading(col, text=headers[col])
            tree.column(col, width=widths[col], anchor="center")

        tree.pack(fill="both", expand=True, padx=15, pady=10)

        for m in messages:
            result_short = (m[6] or "").replace("\r", " ").replace("\n", " ")
            if len(result_short) > 170:
                result_short = result_short[:170] + "..."
            tree.insert("", "end", values=(m[0], m[1], m[2], m[3], m[4], m[5] or "", result_short))

    def export_selected_campaign(self):
        campaign_id = self.get_selected_campaign_id()
        if not campaign_id:
            return
        self.export_campaign_by_id(campaign_id)

    def export_campaign_by_id(self, campaign_id):
        campaign, messages = self.get_campaign_data(campaign_id)

        if not campaign:
            messagebox.showerror("Error", "Campaña no encontrada.")
            return

        default_name = f"reporte_campana_{campaign[0]}_{safe_filename(campaign[1])}.xlsx"

        path = filedialog.asksaveasfilename(
            title="Guardar reporte Excel",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel", "*.xlsx")],
        )

        if not path:
            return

        wb = Workbook()

        ws_summary = wb.active
        ws_summary.title = "Resumen"

        total = len(messages)
        sent = sum(1 for m in messages if m[3] == "sent")
        failed = sum(1 for m in messages if m[3] == "failed")
        queued = sum(1 for m in messages if m[3] == "queued")
        processing = sum(1 for m in messages if m[3] == "processing")

        ws_summary["A1"] = "Reporte NuxSMS"
        ws_summary["A1"].font = Font(size=18, bold=True)

        summary_rows = [
            ("ID campaña", campaign[0]),
            ("Nombre", campaign[1]),
            ("Mensaje", campaign[2]),
            ("Chips", campaign[3]),
            ("Fecha creación", campaign[4]),
            ("Total", total),
            ("Enviados", sent),
            ("Fallidos", failed),
            ("Cola", queued),
            ("Procesando", processing),
            ("Exportado", time.strftime("%Y-%m-%d %H:%M:%S")),
        ]

        row_index = 3
        for label, value in summary_rows:
            ws_summary.cell(row=row_index, column=1, value=label)
            ws_summary.cell(row=row_index, column=2, value=value)
            ws_summary.cell(row=row_index, column=1).font = Font(bold=True)
            row_index += 1

        ws_summary.column_dimensions["A"].width = 22
        ws_summary.column_dimensions["B"].width = 70

        ws = wb.create_sheet("Mensajes")

        headers = [
            "ID",
            "Teléfono",
            "Chip",
            "Estado",
            "Creado",
            "Enviado",
            "Respuesta TG",
        ]

        ws.append(headers)

        header_fill = PatternFill("solid", fgColor="1F2937")
        header_font = Font(color="FFFFFF", bold=True)

        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        for m in messages:
            ws.append([
                m[0],
                m[1],
                m[2],
                m[3],
                m[4],
                m[5] or "",
                m[6] or "",
            ])

        status_col = 4
        for row in range(2, ws.max_row + 1):
            status = ws.cell(row=row, column=status_col).value
            if status == "sent":
                ws.cell(row=row, column=status_col).fill = PatternFill("solid", fgColor="22C55E")
            elif status == "failed":
                ws.cell(row=row, column=status_col).fill = PatternFill("solid", fgColor="EF4444")
            elif status == "queued":
                ws.cell(row=row, column=status_col).fill = PatternFill("solid", fgColor="F59E0B")
            elif status == "processing":
                ws.cell(row=row, column=status_col).fill = PatternFill("solid", fgColor="38BDF8")

        widths = [10, 18, 10, 14, 22, 22, 90]
        for i, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = width

        ws.freeze_panes = "A2"

        try:
            wb.save(path)
            messagebox.showinfo("Exportado", f"Reporte generado correctamente:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar el Excel:\n{e}")

    def delete_selected_campaign(self):
        campaign_id = self.get_selected_campaign_id()
        if not campaign_id:
            return

        if not messagebox.askyesno("Confirmar", f"¿Eliminar campaña {campaign_id} y todos sus SMS?"):
            return

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM messages WHERE campaign_id=?", (campaign_id,))
        cur.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
        conn.commit()
        conn.close()

        self.load_history()
        messagebox.showinfo("OK", "Campaña eliminada.")

    def delete_all_history(self):
        if not messagebox.askyesno("Confirmar", "¿Eliminar TODO el historial local?"):
            return

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM messages")
        cur.execute("DELETE FROM campaigns")
        conn.commit()
        conn.close()

        self.load_history()
        messagebox.showinfo("OK", "Historial eliminado.")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
