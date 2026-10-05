"""
============================================================
 GENERADOR DE REFRESH TOKEN DE SPOTIFY  (uso ÚNICO)
============================================================

Corre en Streamlit Cloud, así que hace el intercambio de tokens
DESDE LA NUBE — tu firewall corporativo no aplica.

Cómo usarlo (una sola vez por cuenta/app de Spotify):

  1. En el dashboard de tu app en developer.spotify.com, agrega la
     URL de ESTA app de Streamlit como Redirect URI, EXACTA, p.ej.:
         https://jukebox-grupoB.streamlit.app
     (sin barra final; debe coincidir carácter por carácter)

  2. En Streamlit Cloud > Settings > Secrets de esta app, pon:
         SPOTIFY_CLIENT_ID     = "..."
         SPOTIFY_CLIENT_SECRET = "..."
         REDIRECT_URI          = "https://jukebox-grupoB.streamlit.app"

  3. Abre la app en el navegador. IMPORTANTE: primero entra a
     spotify.com y verifica que estás logueado con la cuenta del DJ
     correcto (la Premium a la que llegarán los pedidos). El token
     queda atado a la cuenta que apruebe.

  4. Clic en "Conectar con Spotify", aprueba, y Spotify te devolverá
     a esta app. Copia el refresh token que aparece.

  5. Pega ese valor en el secret SPOTIFY_REFRESH_TOKEN de la app
     principal (app.py) del nuevo grupo. Luego puedes borrar o
     apagar esta app generadora.
"""

import requests
import streamlit as st

st.set_page_config(page_title="Refresh Token · Spotify", page_icon="🔑")

TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTH_URL = "https://accounts.spotify.com/authorize"
SCOPES = "user-modify-playback-state user-read-playback-state user-read-currently-playing"

st.title("🔑 Generador de Refresh Token")
st.caption("Uso único para conectar una cuenta de Spotify a un Jukebox DJ.")

# --- Validación de secrets ---------------------------------------
missing = [k for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "REDIRECT_URI")
           if k not in st.secrets]
if missing:
    st.error("Faltan estos secrets en la configuración de la app: " + ", ".join(missing))
    st.stop()

CLIENT_ID = st.secrets["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = st.secrets["SPOTIFY_CLIENT_SECRET"]
REDIRECT_URI = st.secrets["REDIRECT_URI"].strip()

# --- Lectura del callback de Spotify -----------------------------
code = st.query_params.get("code")
error = st.query_params.get("error")

if error:
    st.error(f"Spotify devolvió un error: {error}")
    st.markdown("Vuelve a intentarlo:")
    code = None

if code:
    # Intercambio del código por tokens (ocurre en la nube -> sin firewall)
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
        timeout=15,
    )

    if resp.status_code != 200:
        st.error(f"Error intercambiando el código ({resp.status_code}):")
        st.code(resp.text)
        st.info(
            "Causa más común: el REDIRECT_URI del secret no coincide EXACTAMENTE "
            "con el registrado en el dashboard de Spotify (revisa http/https, "
            "mayúsculas y la barra final)."
        )
        st.stop()

    data = resp.json()
    refresh_token = data.get("refresh_token")

    st.success("✅ ¡Conectado! Copia este refresh token:")
    st.code(refresh_token, language=None)
    st.markdown(
        "Pégalo en el secret **`SPOTIFY_REFRESH_TOKEN`** de la app principal "
        "del nuevo grupo. Después puedes apagar o borrar esta app generadora."
    )
    st.caption("Por seguridad, no compartas este valor: da control de la cola de esa cuenta.")

else:
    # Paso 1: mostrar el enlace de autorización
    st.markdown(
        "**Antes de continuar:** abre [spotify.com](https://open.spotify.com) en otra "
        "pestaña y confirma que estás logueado con la cuenta del **DJ correcto**. "
        "El token quedará atado a esa cuenta."
    )
    auth_link = (
        f"{AUTH_URL}?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&scope={requests.utils.quote(SCOPES)}"
        f"&redirect_uri={requests.utils.quote(REDIRECT_URI)}"
        f"&show_dialog=true"
    )
    st.link_button("🎧 Conectar con Spotify", auth_link, use_container_width=True)
    st.caption(f"Redirect URI en uso: {REDIRECT_URI}")
