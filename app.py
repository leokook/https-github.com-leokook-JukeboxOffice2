"""
============================================================
 JUKEBOX DJ — Streamlit + Spotify + Google Chat
============================================================

Funciones:
  - Buscar canciones y agregarlas a la cola de Spotify del DJ
  - Anuncio de cada pedido en Google Chat (webhook entrante)
  - Historial de pedidos visible en la app
  - Límite de pedidos: 7 por persona por hora

Interfaz en inglés; comentarios en español para mantenimiento.

Secrets requeridos (Streamlit Cloud > Settings > Secrets):

    SPOTIFY_CLIENT_ID     = "..."
    SPOTIFY_CLIENT_SECRET = "..."
    SPOTIFY_REFRESH_TOKEN = "..."
    CHAT_WEBHOOK_URL      = "https://chat.googleapis.com/..."  # opcional
    APP_PASSWORD          = "..."                              # opcional

Nota: el historial y los contadores viven en la memoria de la app.
Si Streamlit Cloud reinicia o duerme la app, se reinician.
"""

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st

# ------------------------------------------------------------
# Configuración
# ------------------------------------------------------------
st.set_page_config(page_title="Jukebox DJ", page_icon="🎧", layout="centered")

SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
TZ = ZoneInfo("America/Toronto")

MAX_REQUESTS_PER_HOUR = 15
RATE_WINDOW_SECONDS = 3600
HISTORY_MAX_SHOWN = 25


# ------------------------------------------------------------
# Almacén compartido entre TODAS las sesiones de la app
# (st.cache_resource devuelve el mismo objeto a todos los usuarios)
# ------------------------------------------------------------
@st.cache_resource
def get_store() -> dict:
    return {
        "lock": threading.Lock(),
        "history": [],           # pedidos: dicts con ts, requester, track, artists, url
        "requests_by_user": {},  # nombre normalizado -> [timestamps]
    }


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def check_rate_limit(requester: str) -> tuple[bool, int, int]:
    """
    Devuelve (permitido, pedidos_usados_en_la_ultima_hora, segundos_hasta_liberar_cupo).
    NO registra el pedido; solo consulta.
    """
    store = get_store()
    now = time.time()
    key = normalize_name(requester)
    with store["lock"]:
        stamps = [t for t in store["requests_by_user"].get(key, []) if now - t < RATE_WINDOW_SECONDS]
        store["requests_by_user"][key] = stamps
        used = len(stamps)
        if used < MAX_REQUESTS_PER_HOUR:
            return True, used, 0
        wait = int(RATE_WINDOW_SECONDS - (now - min(stamps)))
        return False, used, max(wait, 0)


def register_request(requester: str, track: dict) -> None:
    """Registra el pedido en el contador y en el historial (solo tras encolar con éxito)."""
    store = get_store()
    now = time.time()
    key = normalize_name(requester)
    entry = {
        "ts": now,
        "when": datetime.now(TZ).strftime("%I:%M %p").lstrip("0"),
        "requester": requester.strip(),
        "track": track["name"],
        "artists": ", ".join(a["name"] for a in track["artists"]),
        "url": track["external_urls"]["spotify"],
    }
    with store["lock"]:
        store["requests_by_user"].setdefault(key, []).append(now)
        store["history"].insert(0, entry)
        del store["history"][200:]  # techo de memoria


# ------------------------------------------------------------
# Autenticación con Spotify (refresh token -> access token)
# ------------------------------------------------------------
def get_access_token() -> str:
    tok = st.session_state.get("spotify_token")
    if tok and tok["expires_at"] > time.time() + 60:
        return tok["access_token"]

    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": st.secrets["SPOTIFY_REFRESH_TOKEN"],
        },
        auth=(st.secrets["SPOTIFY_CLIENT_ID"], st.secrets["SPOTIFY_CLIENT_SECRET"]),
        timeout=15,
    )
    if resp.status_code != 200:
        st.error(
            "Couldn't connect to Spotify. Please let the DJ know — the account "
            f"may need to be reconnected. (Error {resp.status_code})"
        )
        with st.expander("Technical details"):
            st.code(resp.text)
        st.stop()

    data = resp.json()
    st.session_state["spotify_token"] = {
        "access_token": data["access_token"],
        "expires_at": time.time() + data.get("expires_in", 3600),
    }
    return data["access_token"]


def spotify(method: str, path: str, **kwargs) -> requests.Response:
    headers = {"Authorization": f"Bearer {get_access_token()}"}
    return requests.request(method, SPOTIFY_API + path, headers=headers, timeout=15, **kwargs)


# ------------------------------------------------------------
# Operaciones del jukebox
# ------------------------------------------------------------
def search_tracks(query: str, limit: int = 5) -> list:
    resp = spotify("GET", "/search", params={"q": query, "type": "track", "limit": limit})
    if resp.status_code != 200:
        st.error(f"Spotify search failed ({resp.status_code}). Try again in a moment.")
        return []
    return resp.json()["tracks"]["items"]


def add_to_queue(track_uri: str) -> requests.Response:
    return spotify("POST", "/me/player/queue", params={"uri": track_uri})


def get_now_playing() -> dict | None:
    resp = spotify("GET", "/me/player/currently-playing")
    if resp.status_code != 200 or not resp.text:
        return None
    return resp.json()


def announce_in_chat(track: dict, requester: str) -> None:
    """Publica el pedido en el espacio de Google Chat (si el webhook está configurado)."""
    webhook = st.secrets.get("CHAT_WEBHOOK_URL")
    if not webhook:
        return
    artists = ", ".join(a["name"] for a in track["artists"])
    text = f"🎶 *{track['name']}* — {artists}\nQueued up by *{requester}* 🎧"
    try:
        requests.post(webhook, json={"text": text}, timeout=10)
    except requests.RequestException:
        pass  # el anuncio es cosmético; no rompe el flujo


# ------------------------------------------------------------
# Compuerta opcional de contraseña
# ------------------------------------------------------------
def check_password() -> bool:
    expected = st.secrets.get("APP_PASSWORD")
    if not expected:
        return True
    if st.session_state.get("authed"):
        return True

    st.title("🎧 Jukebox DJ")
    pwd = st.text_input("Office password", type="password")
    if pwd:
        if pwd == expected:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


if not check_password():
    st.stop()


# ------------------------------------------------------------
# Interfaz principal
# ------------------------------------------------------------
st.title("🎧 Jukebox DJ")
st.caption(
    f"Search for a song and add it to the office queue. "
    f"Limit: {MAX_REQUESTS_PER_HOUR} requests per person per hour."
)

# --- Now playing -------------------------------------------------
np = get_now_playing()
if np and np.get("item"):
    item = np["item"]
    artists = ", ".join(a["name"] for a in item["artists"])
    cols = st.columns([1, 5])
    with cols[0]:
        images = item["album"].get("images", [])
        if images:
            st.image(images[-1]["url"], width=64)
    with cols[1]:
        st.markdown(f"**Now playing:** {item['name']} — {artists}")
    st.divider()
else:
    st.info("🔇 Nothing is playing right now. Spotify needs to be playing for requests to work.")

# --- Requester ---------------------------------------------------
requester = st.text_input(
    "Your name (shown in the chat announcement)",
    value=st.session_state.get("requester", ""),
    placeholder="e.g. Andrea",
)
if requester:
    st.session_state["requester"] = requester.strip()

# Cupo restante
if st.session_state.get("requester"):
    _, used, _ = check_rate_limit(st.session_state["requester"])
    remaining = MAX_REQUESTS_PER_HOUR - used
    st.caption(f"🎟️ You have **{remaining}** of {MAX_REQUESTS_PER_HOUR} requests left this hour.")

# --- Search ------------------------------------------------------
query = st.text_input("What do you want to hear?", placeholder="e.g. Mr. Brightside The Killers")

if query:
    results = search_tracks(query)
    if not results:
        st.warning(f'😕 No results for "{query}". Try adding the artist name.')

    for track in results:
        artists = ", ".join(a["name"] for a in track["artists"])
        album = track["album"]["name"]
        images = track["album"].get("images", [])
        duration_s = track["duration_ms"] // 1000
        duration = f"{duration_s // 60}:{duration_s % 60:02d}"

        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 4, 2])
            with c1:
                if images:
                    st.image(images[-1]["url"], width=72)
            with c2:
                st.markdown(f"**{track['name']}**")
                st.caption(f"{artists} · {album} · {duration}")
            with c3:
                if st.button("➕ Queue it", key=f"queue_{track['id']}", use_container_width=True):
                    name = st.session_state.get("requester", "")
                    if not name:
                        st.warning("Enter your name above first 🙂")
                    else:
                        allowed, used, wait = check_rate_limit(name)
                        if not allowed:
                            mins = max(1, wait // 60)
                            st.error(
                                f"🎟️ You've used all {MAX_REQUESTS_PER_HOUR} requests for this hour. "
                                f"Another slot opens in about {mins} min."
                            )
                        else:
                            resp = add_to_queue(track["uri"])
                            if resp.status_code in (200, 202, 204):
                                register_request(name, track)
                                st.success(f"🎶 *{track['name']}* added to the queue!")
                                announce_in_chat(track, name)
                                st.balloons()
                            elif resp.status_code == 404:
                                st.error(
                                    "⏸️ No active playback device. "
                                    "Ask the DJ to hit play on Spotify and try again."
                                )
                            elif resp.status_code == 403:
                                st.error("🔒 Spotify rejected the request (403). Is the account still Premium?")
                            else:
                                st.error(f"⚠️ Error {resp.status_code}: {resp.text}")

# --- Request history ---------------------------------------------
st.divider()
history = get_store()["history"]
with st.expander(f"📜 Request history ({len(history)})", expanded=False):
    if not history:
        st.caption("No requests yet. Be the first! 🎤")
    else:
        for h in history[:HISTORY_MAX_SHOWN]:
            st.markdown(
                f"`{h['when']}` &nbsp; [{h['track']}]({h['url']}) — {h['artists']} "
                f"&nbsp;·&nbsp; requested by **{h['requester']}**"
            )
        if len(history) > HISTORY_MAX_SHOWN:
            st.caption(f"… and {len(history) - HISTORY_MAX_SHOWN} more.")

st.caption("Jukebox DJ · built with Streamlit + the Spotify API · requests play on the DJ's account 🎛️")

# ------------------------------------------------------------
# NOTA SOBRE PERSISTENCIA:
# El historial y los contadores viven en memoria (st.cache_resource),
# compartidos entre todos los usuarios mientras la app esté despierta.
# Si la app se reinicia o duerme, se reinician. Para persistencia real,
# la mejora natural es una tabla en Supabase (requests: ts, requester,
# track, artists, url) y reemplazar register_request/check_rate_limit
# por consultas a esa tabla.
# ------------------------------------------------------------
