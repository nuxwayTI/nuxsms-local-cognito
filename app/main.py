import tkinter as tk
from tkinter import messagebox
from auth import login


class App:
    def __init__(self, root):
        self.root = root
        root.title("NuxSMS Local")
        root.geometry("700x500")
        root.configure(bg="#0b1020")

        tk.Label(root, text="NUXSMS LOCAL", font=("Arial", 28, "bold"),
                 fg="white", bg="#0b1020").pack(pady=30)

        self.status = tk.Label(root, text="No autenticado",
                               fg="red", bg="#0b1020", font=("Arial", 14))
        self.status.pack()

        tk.Button(root, text="Iniciar sesión",
                  command=self.do_login,
                  bg="orange", font=("Arial", 12)).pack(pady=20)

        self.output = tk.Text(root, height=10, bg="black", fg="white")
        self.output.pack(padx=20, pady=20)

    def log(self, txt):
        self.output.insert(tk.END, txt + "\n")

    def do_login(self):
        try:
            self.log("Abriendo Cognito...")
            user = login()

            email = user.get("email", "sin email")

            self.status.config(text=f"Autenticado: {email}", fg="green")
            self.log("LOGIN OK")
            self.log(str(user))

        except Exception as e:
            self.log("ERROR: " + str(e))
            messagebox.showerror("Error", str(e))


root = tk.Tk()
app = App(root)
root.mainloop()
