import json
import os
import tkinter as tk
from tkinter import messagebox

from auth import login_with_cognito

SESSION_FILE = "session.json"


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("NuxSMS Local - Cognito Test")
        self.root.geometry("720x500")
        self.root.configure(bg="#0b1020")

        tk.Label(
            root,
            text="NUXSMS LOCAL",
            font=("Arial", 28, "bold"),
            fg="#f8fafc",
            bg="#0b1020"
        ).pack(pady=(35, 5))

        tk.Label(
            root,
            text="Prueba de autenticación AWS Cognito",
            font=("Arial", 13),
            fg="#cbd5e1",
            bg="#0b1020"
        ).pack(pady=(0, 25))

        self.status = tk.Label(
            root,
            text="Estado: no autenticado",
            font=("Arial", 14, "bold"),
            fg="#ef4444",
            bg="#0b1020"
        )
        self.status.pack(pady=10)

        tk.Button(
            root,
            text="Iniciar sesión con Cognito",
            command=self.login,
            bg="#f59e0b",
            fg="#111827",
            font=("Arial", 12, "bold"),
            padx=18,
            pady=8
        ).pack(pady=12)

        tk.Button(
            root,
            text="Cerrar sesión local",
            command=self.logout_local,
            bg="#2563eb",
            fg="white",
            font=("Arial", 11, "bold"),
            padx=18,
            pady=7
        ).pack(pady=5)

        self.output = tk.Text(
            root,
            height=12,
            width=82,
            bg="#030712",
            fg="#e5e7eb"
        )
        self.output.pack(padx=20, pady=20)

        self.load_session()

    def write(self, text):
        self.output.insert(tk.END, text + "\n")
        self.output.see(tk.END)

    def save_session(self, data):
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_session(self):
        if not os.path.exists(SESSION_FILE):
            return

        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            claims = data.get("claims", {})
            email = claims.get("email", "usuario")
            self.status.config(text=f"Estado: sesión guardada - {email}", fg="#22c55e")
            self.write(f"Sesión local encontrada: {email}")

        except Exception:
            pass

    def login(self):
        try:
            self.write("Abriendo navegador para login...")
            result = login_with_cognito()

            claims = result["claims"]
            email = claims.get("email", "sin email")
            username = claims.get("cognito:username", "")

            self.save_session(result)

            self.status.config(text=f"Estado: autenticado - {email}", fg="#22c55e")

            self.write("Login correcto")
            self.write(f"Email: {email}")
            self.write(f"Usuario: {username}")

            messagebox.showinfo("OK", f"Autenticado: {email}")

        except Exception as e:
            self.status.config(text="Estado: error de autenticación", fg="#ef4444")
            self.write("ERROR: " + str(e))
            messagebox.showerror("Error", str(e))

    def logout_local(self):
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)

        self.status.config(text="Estado: no autenticado", fg="#ef4444")
        self.write("Sesión local eliminada")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
