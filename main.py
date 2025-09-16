import traceback
import os
import asyncio
import httpx
import gspread
import time
import json
from fastapi import FastAPI, Request, Response, BackgroundTasks
from urllib.parse import quote
from google.oauth2.service_account import Credentials


# --- CONFIGURACIÓN ---
app = FastAPI()
port = int(os.environ.get("PORT", 8000))

# --- CACHÉ SIMPLE PARA LOS CONTACTOS ---
cached_contacts = {}
CACHE_DURATION_SECONDS = 300 # 5 minutos
last_cache_time = 0

# --- LÓGICA PARA CONECTARSE A GOOGLE SHEETS (ACTUALIZADA) ---
# --- LÓGICA PARA CONECTARSE A GOOGLE SHEETS (CORREGIDA) ---
def get_contacts_from_sheet():
    global last_cache_time, cached_contacts

    # La lógica del caché no cambia
    if time.time() - last_cache_time < CACHE_DURATION_SECONDS:
        return cached_contacts

    print("--- INICIANDO DIAGNÓSTICO DE GOOGLE SHEETS ---")
    try:
        # 1. Verificamos si la variable de entorno existe
        print("1. Intentando leer la variable de entorno 'GOOGLE_CREDS_JSON'...")
        creds_json_string = os.environ.get("GOOGLE_CREDS_JSON")

        if not creds_json_string:
            raise ValueError("¡ERROR CRÍTICO! La variable de entorno no fue encontrada por la aplicación.")

        # 2. Mostramos información sobre la variable leída
        print("2. Variable leída con éxito.")
        print(f"   - Tipo de dato: {type(creds_json_string)}")
        print(f"   - Longitud del string: {len(creds_json_string)} caracteres")
        print(f"   - Primeros 50 caracteres: {creds_json_string[:50]}...")
        
        # 3. Intentamos convertir el string a un diccionario JSON
        print("3. Intentando decodificar el string a JSON...")
        creds_dict = json.loads(creds_json_string)
        print("4. ¡Éxito! El JSON fue decodificado correctamente.")

        # El resto de la lógica sigue igual
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # ... (el resto de la función no cambia)

        sheet = client.open("Control API Alertas").worksheet("Control")
        records = sheet.get_all_records()
        
        all_contacts = {}
        for row in records:
            is_active = str(row.get("active", "FALSE")).upper() == 'TRUE'
            if is_active:
                user = row.get("user")
                if user:
                    if user not in all_contacts:
                        all_contacts[user] = []
                    all_contacts[user].append({
                        "phone": str(row.get("phone")),
                        "apikey": str(row.get("apikey")),
                        "message": row.get("message")
                    })
        
        cached_contacts = all_contacts
        last_cache_time = time.time()
        print(f"5. Contactos actualizados desde Google Sheets.")
        return cached_contacts

    except Exception as e:
        # Esta parte ahora nos dará el error exacto y la línea donde ocurre
        print("\n❌❌❌ OCURRIÓ UN ERROR DETALLADO ❌❌❌")
        traceback.print_exc()
        print("--- FIN DEL DIAGNÓSTICO --- \n")
        return cached_contacts
    
    
# --- FUNCIÓN DE ENVÍO (sin cambios) ---
async def send_notifications(contacts_list: list = []):
    """Envía mensajes de WhatsApp en secuencia con una pausa."""
    print('🚨 Activando envío de mensajes...')
    async with httpx.AsyncClient() as client:
        for contact in contacts_list:
            encoded_message = quote(contact["message"])
            url = f"https://api.callmebot.com/whatsapp.php?phone={contact['phone']}&text={encoded_message}&apikey={contact['apikey']}"
            
            try:
                response = await client.get(url)
                response.raise_for_status()
                print(f"✅ Mensaje enviado a {contact['phone']}: {response.text}")
                await asyncio.sleep(1)
            except httpx.RequestError as e:
                print(f"❌ Error enviando a {contact['phone']}: {e}")

# --- RUTAS DE LA API (sin cambios) ---
@app.get("/uptimerobot")
async def uptime_check():
    if request.method == "GET":
        return "OK", 200  # Para UptimeRobot o pruebas básicas

@app.post("/{user}")
async def handle_alert(user: str, request: Request, background_tasks: BackgroundTasks):
    """
    Responde a Alexa y ejecuta el envío de mensajes en segundo plano.
    """
    all_contacts = get_contacts_from_sheet()
    contacts_to_send = all_contacts.get(user)

    print(f"📢 Llamada recibida para el usuario: {user}")

    if not contacts_to_send:
        print(f"❌ Usuario '{user}' no encontrado o sin contactos activos en Google Sheets.")
        return {"version": "1.0", "response": {"outputSpeech": {"type": "PlainText", "text": "Error: usuario no encontrado o sin contactos activos."}, "shouldEndSession": True}}
    
    try:
        body = await request.json()
    except Exception:
        body = {}

    request_type = body.get("request", {}).get("type", "IntentRequest")
    intent_name = body.get("request", {}).get("intent", {}).get("name", "ayuda")

    if request_type == 'LaunchRequest' or (request_type == 'IntentRequest' and intent_name == 'ayuda'):
        background_tasks.add_task(send_notifications, contacts_to_send)
        return {"version": "1.0", "response": {"outputSpeech": {"type": "PlainText", "text": f"Entendido {user}, ya estoy pidiendo ayuda."}, "shouldEndSession": True}}
    else:
        return {"version": "1.0", "response": {"outputSpeech": {"type": "PlainText", "text": "No entendí tu solicitud. Intenta decir: Alexa, pide ayuda."}, "shouldEndSession": True}}

# Para pruebas locales
if __name__ == "__main__":
    if not os.environ.get("GOOGLE_CREDS_JSON"):
        print("ADVERTENCIA: La variable GOOGLE_CREDS_JSON no está configurada. La API no podrá leer de Google Sheets.")
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
