import base64
import hashlib
import http.server
import json
import os
import socketserver
import threading
import time
import urllib.parse
import webbrowser

import jwt
import requests

from config import *

AUTH_RESULT = {"code": None, "error": None}


def base64url(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def create_pkce_pair():
    verifier = base64url(os.urandom(40))
    challenge = base64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/callback":
            if "code" in params:
                AUTH_RESULT["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"""
                <html>
                <body style="font-family:Arial;text-align:center;margin-top:60px;">
                    <h2>Login correcto</h2>
                    <p>Puedes cerrar esta ventana y volver al programa.</p>
                </body>
                </html>
                """)
            else:
                AUTH_RESULT["error"] = str(params)
                self.send_response(400)
                self.end_headers()

        elif parsed.path == "/logout":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html>
            <body style="font-family:Arial;text-align:center;margin-top:60px;">
                <h2>Sesion Cognito cerrada</h2>
                <p>Ahora vuelve al programa.</p>
            </body>
            </html>
            """)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        return


def start_server():
    server = socketserver.TCPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def exchange_code(code, verifier):
    url = f"{COGNITO_DOMAIN}/oauth2/token"

    data = {
        "grant_type": "authorization_code",
        "client_id": APP_CLIENT_ID,
        "code": code,
        "redirect_uri": CALLBACK_URL,
        "code_verifier": verifier
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(url, data=data, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def get_jwks():
    url = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def decode_token(token):
    jwks = get_jwks()
    header = jwt.get_unverified_header(token)

    key = None
    for k in jwks["keys"]:
        if k["kid"] == header["kid"]:
            key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
            break

    if key is None:
        raise Exception("No se encontro llave publica Cognito")

    issuer = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"

    return jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=APP_CLIENT_ID,
        issuer=issuer
    )


def open_logout_first():
    logout_params = {
        "client_id": APP_CLIENT_ID,
        "logout_uri": LOGOUT_URL
    }

    logout_url = f"{COGNITO_DOMAIN}/logout?{urllib.parse.urlencode(logout_params)}"
    webbrowser.open(logout_url)
    time.sleep(2)


def login():
    AUTH_RESULT["code"] = None
    AUTH_RESULT["error"] = None

    verifier, challenge = create_pkce_pair()

    params = {
        "client_id": APP_CLIENT_ID,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": CALLBACK_URL,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "login"
    }

    login_url = f"{COGNITO_DOMAIN}/oauth2/authorize?{urllib.parse.urlencode(params)}"

    server = start_server()

    try:
        open_logout_first()
        webbrowser.open(login_url)

        start = time.time()

        while time.time() - start < 180:
            if AUTH_RESULT["code"]:
                tokens = exchange_code(AUTH_RESULT["code"], verifier)

                if "id_token" not in tokens:
                    raise Exception("Cognito no devolvio id_token: " + str(tokens))

                claims = decode_token(tokens["id_token"])
                return claims

            if AUTH_RESULT["error"]:
                raise Exception(AUTH_RESULT["error"])

            time.sleep(0.5)

        raise Exception("Timeout login Cognito")

    finally:
        server.shutdown()
        server.server_close()
