"""
FILE SMASH - servidor de salas (relay)

No simula el juego: solo une al HOST de una sala con los demas jugadores y les
reenvia los mensajes. Todos se conectan HACIA el servidor, asi nadie necesita
abrir puertos en su router.

Uso local / LAN:   python relay_server.py            (puerto 8765)
En Render:         Start Command  ->  python relay_server.py
                   (Render le da el puerto en la variable PORT; ya esta contemplado)
Requisito:         pip install websockets   (version 12 o mayor)

Protocolo (JSON, lo usa file_smash.py):
  cliente -> server : {"t":"host"}                      crea una sala
                      {"t":"join","code":"ABCDE"}       entra a una sala ("*" = la unica sala)
  server  -> host   : {"t":"hosted","code":"ABCDE"}
                      {"t":"peer_join","pid":N} / {"t":"peer_leave","pid":N}
                      {"from":N,"d":{...}}              mensaje de un jugador
  host    -> server : {"to":"all"|N,"d":{...}}          a todos / a un jugador
                      <bytes>                           a todos (snapshots comprimidos)
  server  -> cliente: {"t":"joined","pid":N} / {"t":"error","msg":"..."} / {"t":"host_left"}
"""

import asyncio
import json
import os
import random
import threading

import websockets

try:                                    # websockets >= 13
    from websockets.asyncio.server import serve
except ImportError:                     # versiones anteriores
    serve = websockets.serve

MAX_PLAYERS = 8                         # host + 7 jugadores
ALPHABET    = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sin 0/O/1/I para no confundir
ROOMS       = {}                        # codigo -> Room


class Room:
    def __init__(self, code, host):
        self.code    = code
        self.host    = host
        self.clients = {}               # pid -> websocket

    def free_pid(self):
        for pid in range(1, MAX_PLAYERS):
            if pid not in self.clients:
                return pid
        return None


def new_code():
    while True:
        code = "".join(random.choice(ALPHABET) for _ in range(5))
        if code not in ROOMS:
            return code


async def safe_send(ws, data):
    try:
        await ws.send(data)
    except Exception:
        pass


async def broadcast(room, data):
    targets = list(room.clients.values())
    if targets:
        await asyncio.gather(*(safe_send(c, data) for c in targets))


async def handler(ws):
    room = None
    pid  = None
    try:
        async for raw in ws:
            # ── aun sin sala: el primer mensaje debe ser host / join ──
            if room is None:
                try:
                    msg = json.loads(raw)
                    t   = msg.get("t")
                except Exception:
                    await safe_send(ws, json.dumps({"t": "error", "msg": "mensaje invalido"}))
                    continue
                if t == "host":
                    code = new_code()
                    room = Room(code, ws)
                    ROOMS[code] = room
                    pid = 0
                    await safe_send(ws, json.dumps({"t": "hosted", "code": code}))
                    print(f"[sala {code}] creada")
                elif t == "join":
                    code = str(msg.get("code", "")).strip().upper().replace("-", "")
                    target = None
                    if code == "*" and len(ROOMS) == 1:
                        target = next(iter(ROOMS.values()))
                    else:
                        target = ROOMS.get(code)
                    if target is None:
                        await safe_send(ws, json.dumps({"t": "error", "msg": "Sala no encontrada"}))
                        continue
                    new_pid = target.free_pid()
                    if new_pid is None:
                        await safe_send(ws, json.dumps({"t": "error", "msg": "La sala esta llena (max 8)"}))
                        continue
                    room = target
                    pid  = new_pid
                    room.clients[pid] = ws
                    await safe_send(ws, json.dumps({"t": "joined", "pid": pid}))
                    await safe_send(room.host, json.dumps({"t": "peer_join", "pid": pid}))
                    print(f"[sala {room.code}] entra jugador {pid} ({len(room.clients) + 1}/{MAX_PLAYERS})")
                else:
                    await safe_send(ws, json.dumps({"t": "error", "msg": "se esperaba host o join"}))
                continue

            # ── dentro de una sala ──────────────────────────────────
            if ws is room.host:
                if isinstance(raw, (bytes, bytearray)):
                    await broadcast(room, bytes(raw))          # snapshots: a todos
                    continue
                try:
                    msg = json.loads(raw)
                    data = msg["d"]
                    to = msg.get("to", "all")
                except Exception:
                    continue
                if isinstance(data, dict) and data.get("t") == "ping":
                    continue
                out = json.dumps(data, separators=(",", ":"))
                if to == "all":
                    await broadcast(room, out)
                else:
                    dest = room.clients.get(to)
                    if dest is not None:
                        await safe_send(dest, out)
            else:
                if isinstance(raw, (bytes, bytearray)):
                    continue                                   # los clientes solo mandan JSON
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                if isinstance(data, dict) and data.get("t") == "ping":
                    continue
                await safe_send(room.host, json.dumps({"from": pid, "d": data}, separators=(",", ":")))
    except websockets.ConnectionClosed:
        pass
    except Exception as e:                                     # nunca tumbar el servidor por un cliente
        print("[error]", repr(e))
    finally:
        if room is not None:
            if ws is room.host:
                ROOMS.pop(room.code, None)
                print(f"[sala {room.code}] cerrada (el host salio)")
                for c in list(room.clients.values()):
                    await safe_send(c, json.dumps({"t": "host_left"}))
                    try:
                        await c.close()
                    except Exception:
                        pass
            else:
                room.clients.pop(pid, None)
                await safe_send(room.host, json.dumps({"t": "peer_leave", "pid": pid}))
                print(f"[sala {room.code}] sale jugador {pid}")


async def _main(host, port):
    async with serve(handler, host, port, max_size=2 ** 22):
        print(f"Servidor de File Smash escuchando en {host}:{port}")
        await asyncio.Future()


def start_background(port=8765, host="0.0.0.0"):
    """Arranca el servidor en un hilo (lo usa el juego para las salas LAN).
    Devuelve (hilo, funcion_para_detener, error_o_None)."""
    state = {"err": None, "loop": None, "stop": None}
    ready = threading.Event()

    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        state["loop"] = loop

        async def run():
            state["stop"] = asyncio.Event()
            try:
                async with serve(handler, host, port, max_size=2 ** 22):
                    ready.set()
                    await state["stop"].wait()
            except OSError as e:
                state["err"] = e
                ready.set()

        try:
            loop.run_until_complete(run())
        finally:
            ready.set()
            loop.close()

    th = threading.Thread(target=runner, daemon=True)
    th.start()
    ready.wait(8)

    def stop():
        if state["loop"] and state["stop"]:
            state["loop"].call_soon_threadsafe(state["stop"].set)

    return th, stop, state["err"]


if __name__ == "__main__":
    asyncio.run(_main("0.0.0.0", int(os.environ.get("PORT", "8765"))))