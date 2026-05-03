# NuxSMS Local Cognito

EXE local con:
- Login AWS Cognito
- Sesión local válida 24 horas
- SQLite local
- Campañas SMS
- Round robin por chips
- Conexión TG1600/TG Series puerto 5038

## Ejecutar

cd app
pip install -r requirements.txt
python main.py

## Crear EXE con logo

python -m PyInstaller --onefile --windowed --add-data "logo.png;." main.py

## Archivos locales

local_config.json
session.json
nuxsms_local.db

