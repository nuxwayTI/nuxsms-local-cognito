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

from auth import login
from tg1600 import TG1600Client

CONFIG_FILE = "local_config.json"
SESSION_FILE = "session.json"
DB_FILE = "nuxsms_local.db"
COUNTRY_CODE = "591"
SESSION_MAX_HOURS = 24


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

    age_seconds = time.time() - float(login_time)
    max_seconds = SESSION_MAX_HOURS * 60 * 60

    return age_seconds < max_seconds


def session_remaining_text(session):
    if not session or not session.get("login_time"):
        return "0h"

    age_seconds = time.time() - float(session["login_time"])
    max_seconds = SESSION_MAX_HOURS * 60 * 60
    remaining = max_seconds - age_seconds

    if remaining <= 0:
        return "expirada"

    hours = int(remaining // 3600)
    minutes = int((remaining % 3600) // 60)

    return f"{hours}h {minutes}m"


def normalize_phone(phone):
    phone = str(phone).strip()
    phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

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
        self.root.geometry("1000x740")
        self.root.configure(bg="#0b1020")

        self.authenticated = False
        self.user_email = None
        self.session = None
        self.cfg = load_config()
        self.running = False
        self.worker = None
        self.logo_img = None

        self.setup_ui()
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
        self.tab_history = tk.Frame(self.notebook, bg="#111827")

        self.notebook.add(self.tab_login, text="Login")
        self.notebook.add(self.tab_config, text="Configuración TG")
        self.notebook.add(self.tab_campaign, text="Lanzador SMS")
        self.notebook.add(self.tab_history, text="Historial")

        self.build_login_tab()
        self.build_config_tab()
        self.build_campaign_tab()
        self.build_history_tab()

        self.lock_tabs()
        self.root.after(60000, self.check_session_timer)

    def lock_tabs(self):
        if not self.authenticated:
            self.notebook.tab(1, state="disabled")
            self.notebook.tab(2, state="disabled")
            self.notebook.tab(3, state="disabled")
        else:
            self.notebook.tab(1, state="normal")
            self.notebook.tab(2, state="normal")
            self.notebook.tab(3, state="normal")

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
            width=100,
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
            width=118,
            bg="#030712",
            fg="#e5e7eb",
        )
        self.send_log.pack(padx=20, pady=10)

    def build_history_tab(self):
        buttons = tk.Frame(self.tab_history, bg="#111827")
        buttons.pack(anchor="w", padx=20, pady=12)

        tk.Button(
            buttons,
            text="Actualizar historial",
            command=self.load_history,
            bg="#2563eb",
            fg="white",
        ).pack(side="left", padx=5)

        tk.Button(
            buttons,
            text="Eliminar historial local",
            command=self.delete_all_history,
            bg="#ef4444",
            fg="white",
        ).pack(side="left", padx=5)

        self.history_text = tk.Text(
            self.tab_history,
            height=25,
            width=118,
            bg="#030712",
            fg="#e5e7eb",
        )
        self.history_text.pack(padx=20, pady=10)

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
            self.log_login(f"Validez restante: {session_remaining_text(session)}")
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
            self.log_login(f"Sesión válida por {SESSION_MAX_HOURS} horas.")

            self.lock_tabs()
            self.notebook.select(self.tab_config)

        except Exception as e:
            self.status.config(text="Error de autenticación", fg="#ef4444")
            self.log_login("ERROR: " + str(e))
            messagebox.showerror("Error", str(e))

    def do_logout(self):
        clear_session()
        self.authenticated = False
        self.user_email = None
        self.session = None
        self.status.config(text="Estado: no autenticado", fg="#ef4444")
        self.lock_tabs()
        self.notebook.select(self.tab_login)
        self.log_login("Sesión local cerrada.")

    def check_session_timer(self):
        if self.authenticated:
            if not session_is_valid(self.session):
                self.running = False
                clear_session()
                self.authenticated = False
                self.status.config(text="Sesión expirada. Inicia sesión otra vez.", fg="#ef4444")
                self.lock_tabs()
                self.notebook.select(self.tab_login)
                messagebox.showwarning("Sesión expirada", "Han pasado 24 horas. Debes iniciar sesión nuevamente.")
            else:
                self.status.config(
                    text=f"Autenticado: {self.user_email} | {session_remaining_text(self.session)}",
                    fg="#22c55e",
                )

        self.root.after(60000, self.check_session_timer)

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

                cur.execute(
                    """
                    SELECT id, phone, text, chip
                    FROM messages
                    WHERE status='queued'
                    ORDER BY id ASC
                    LIMIT 1
                    """
                )

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

                self.log_send(f"Enviando ID {msg_id} a {phone} por chip {chip}")

                result = tg.send_sms(
                    chip=chip,
                    to_number=phone,
                    message=text,
                    message_id=msg_id,
                )

                status = "sent" if result["success"] else "failed"
                sent_at = time.strftime("%Y-%m-%d %H:%M:%S")

                conn = sqlite3.connect(DB_FILE)
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE messages
                    SET status=?, result=?, sent_at=?
                    WHERE id=?
                    """,
                    (status, result["raw"][:3000], sent_at, msg_id),
                )
                conn.commit()
                conn.close()

                self.log_send(
                    f"Resultado ID {msg_id}: {status} | chip web {result['requested_chip']} | TG {result['real_chip']}"
                )

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
               COUNT(m.id),
               SUM(CASE WHEN m.status='sent' THEN 1 ELSE 0 END),
               SUM(CASE WHEN m.status='failed' THEN 1 ELSE 0 END),
               SUM(CASE WHEN m.status='queued' THEN 1 ELSE 0 END),
               SUM(CASE WHEN m.status='processing' THEN 1 ELSE 0 END)
        FROM campaigns c
        LEFT JOIN messages m ON m.campaign_id = c.id
        GROUP BY c.id
        ORDER BY c.id DESC
        """)

        rows = cur.fetchall()
        conn.close()

        self.history_text.delete("1.0", tk.END)

        for r in rows:
            self.history_text.insert(
                tk.END,
                f"Campaña {r[0]} | {r[1]} | Chips {r[2]} | Total {r[4]} | Enviados {r[5] or 0} | Fallidos {r[6] or 0} | Cola {r[7] or 0} | Procesando {r[8] or 0} | {r[3]}\n",
            )

    def delete_all_history(self):
        if not messagebox.askyesno("Confirmar", "¿Eliminar todo el historial local?"):
            return

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM messages")
        cur.execute("DELETE FROM campaigns")
        conn.commit()
        conn.close()

        self.load_history()
        messagebox.showinfo("OK", "Historial eliminado")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
