import socket
import time
import urllib.parse


class TG1600Client:
    def __init__(self, host, port, username, password, timeout=10):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.timeout = timeout
        self.sock = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

        login_cmd = (
            "Action: Login\r\n"
            f"Username: {self.username}\r\n"
            f"Secret: {self.password}\r\n\r\n"
        )

        self.sock.sendall(login_cmd.encode())
        response = self._read_some()

        if "Response: Success" not in response:
            raise Exception(f"TG login failed: {response}")

        return True

    def send_sms(self, chip, to_number, message, message_id):
        real_chip = int(chip)

        safe_message = urllib.parse.quote(message)
        clean_number = str(to_number).replace("+", "").replace(" ", "")

        cmd = (
            "Action: smscommand\r\n"
            f"command: gsm send sms {real_chip} {clean_number} \"{safe_message}\" {message_id}\r\n\r\n"
        )

        self.sock.sendall(cmd.encode())
        response = self._read_until_marker("--END SMS EVENT--", timeout=40)

        success = False
        if "Status: 1" in response:
            success = True
        elif "Response: Success" in response:
            success = True
        elif "OK" in response:
            success = True

        return {
            "success": success,
            "raw": response,
            "requested_chip": chip,
            "real_chip": real_chip,
        }

    def _read_some(self):
        time.sleep(0.5)
        return self.sock.recv(4096).decode(errors="ignore")

    def _read_until_marker(self, marker, timeout=40):
        old_timeout = self.sock.gettimeout()
        self.sock.settimeout(timeout)

        data = ""
        start = time.time()

        while marker not in data and time.time() - start < timeout:
            try:
                chunk = self.sock.recv(4096).decode(errors="ignore")
                if not chunk:
                    break
                data += chunk
            except socket.timeout:
                break

        self.sock.settimeout(old_timeout)
        return data

    def close(self):
        if self.sock:
            self.sock.close()

