import base64
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import threading
import time
import urllib.parse
import webbrowser

import jwt
import requests

from config import (
    COGNITO_DOMAIN,
    USER_POOL_ID,
    APP_CLIENT_ID,
    CALLBACK_HOST,
    CALLBACK_PORT,
    CALLBACK_URL,
    SCOPES,
)

AUTH_RESULT = {
    "code": None,
    "error": None
}


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def create_pkce_pair():
    verifier = base64url(os.urandom(40))
    challenge = base64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/callback":
            if "code" in params:
                AUTH_RESULT["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("""
                <html>
                <body style="font-family:Arial;text-align:center;margin-top:60px;">
                    <h1>Login correcto</h1>
                    <p>Ya puedes volver al programa NuxSMS.</p>
                </body>
                </html>
                """.encode("utf-8"))
            else:
                AUTH_RESULT["error"] = str(params)
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_callback_server():
    server = socketserver.TCPServer((CALLBACK_HOST, CALLBACK_PORT), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def exchange_code_for_tokens(code, code_verifier):
    token_url = f"{COGNITO_DOMAIN}/oauth2/token"

    data = {
        "grant_type": "authorization_code",
        "client_id": APP_CLIENT_ID,
        "code": code,
        "redirect_uri": CALLBACK_URL,
        "code_verifier": code_verifier
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(token_url, data=data, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def get_jwks():
    jwks_url = f"https://cognito-idp.us-east-2.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
    response = requests.get(jwks_url, timeout=30)
    response.raise_for_status()
    return response.json()


def decode_id_token(id_token):
    jwks = get_jwks()
    unverified_header = jwt.get_unverified_header(id_token)
    key_id = unverified_header["kid"]

    public_key = None
    for key in jwks["keys"]:
        if key["kid"] == key_id:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
            break

    if public_key is None:
        raise Exception("No se encontró la llave pública del token")

    issuer = f"https://cognito-idp.us-east-2.amazonaws.com/{USER_POOL_ID}"

    claims = jwt.decode(
        id_token,
        public_key,
        algorithms=["RS256"],
        audience=APP_CLIENT_ID,
        issuer=issuer
    )

    return claims


def login_with_cognito(timeout_seconds=180):
    AUTH_RESULT["code"] = None
    AUTH_RESULT["error"] = None

    code_verifier, code_challenge = create_pkce_pair()
    state = secrets.token_urlsafe(24)

    params = {
        "client_id": APP_CLIENT_ID,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": CALLBACK_URL,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }

    auth_url = f"{COGNITO_DOMAIN}/oauth2/authorize?{urllib.parse.urlencode(params)}"

    server = start_callback_server()

    try:
        webbrowser.open(auth_url)

        start = time.time()
        while time.time() - start < timeout_seconds:
            if AUTH_RESULT["code"]:
                tokens = exchange_code_for_tokens(AUTH_RESULT["code"], code_verifier)
                claims = decode_id_token(tokens["id_token"])

                return {
                    "tokens": tokens,
                    "claims": claims
                }

            if AUTH_RESULT["error"]:
                raise Exception(AUTH_RESULT["error"])

            time.sleep(0.3)

        raise TimeoutError("Tiempo agotado esperando login")

    finally:
        server.shutdown()
        server.server_close()
