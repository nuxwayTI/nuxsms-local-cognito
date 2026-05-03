# nuxsms-local-cognito
# NuxSMS Local Cognito

Prueba de login AWS Cognito para un EXE local.

## Configuración Cognito

Callback URL:

http://localhost:8765/callback

Logout URL:

http://localhost:8765/logout

OAuth:

Authorization code grant + PKCE

Scopes:

openid email profile

## Ejecutar

cd app
pip install -r requirements.txt
python main.py

## Compilar EXE

python -m PyInstaller --onefile --windowed main.py
