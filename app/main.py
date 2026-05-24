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

# SESION REAL 24 HORAS
SESSION_MAX_HOURS = 24
SESSION_TEST_SECONDS = None


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


if __name__ == "__main__":
    root = tk.Tk()

    # ICONO DEL EXE / BARRA / APP
    try:
        root.iconbitmap(resource_path("icon.ico"))
    except Exception:
        pass

    app = App(root)
    root.mainloop()
