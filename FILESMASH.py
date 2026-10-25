"""
Battle royale estilo Smash Bros. Los archivos de la carpeta PVP pelean.
El perdedor cae del escenario y es borrado del disco. 🔥
Personajes: Kirby (habilidades X), None (solo golpe y salto),
Kris (espada, save point, soul, ACT) y Gamer64 (3 fases).
Modos: VS CPU (el perdedor se borra del disco) y MULTIJUGADOR (hasta 8, no borra nada).
Los stats dependen del PESO del archivo: pesado = lento y fuerte, liviano = rapido y facil de lanzar.
"""

import pygame
import os, sys, math, random
import json, zlib, base64, threading, queue, socket, time, io, subprocess, tempfile
from functools import lru_cache
from PIL import Image as PILImage

# Multijugador: pip install websockets
try:
    from websockets.sync.client import connect as ws_connect
    HAS_WS = True
except Exception:
    HAS_WS = False

# Opening en video: pip install imageio-ffmpeg
try:
    import imageio_ffmpeg
    HAS_FFMPEG = True
except Exception:
    HAS_FFMPEG = False

# ═══════════════════════ CONFIGURACION ═══════════════════════
if getattr(sys, "frozen", False):                      # ejecutando como .exe (PyInstaller)
    BASE_DIR  = os.path.dirname(sys.executable)        # carpeta donde esta el .exe
else:
    BASE_DIR  = os.path.dirname(os.path.abspath(__file__))   # carpeta donde esta este archivo
PVP_FOLDER    = os.path.join(BASE_DIR, "PVP")
WIN_W, WIN_H  = 1000, 620
FPS           = 60
MAX_POR_RONDA = 12
SPRITE_SIZE   = 52
GRAVITY       = 0.55
JUMP_FORCE    = -13
MOVE_SPEED    = 3.2
AI_SPEED      = 2.6
ATTACK_RANGE  = 70
ATTACK_CD     = 45
KNOCKBACK_BASE= 6.0
DAMAGE_SCALE  = 0.045
MAX_DAMAGE    = 999

# ── Multijugador ─────────────────────────────────────────────
SERVER_URL    = ""     # tu servidor de salas, ej: "wss://file-smash.onrender.com" (ver RELAYSERV.py)
LAN_PORT      = 8765   # puerto de las salas en red local
MAX_PLAYERS   = 8
NET_TICK      = 2      # el host manda el estado cada 2 frames (30 veces por segundo)
MP_STAKES     = True   # multijugador: el que pierde BORRA su archivo. Pon False para practicar sin riesgo.

# ── Menu / opening ───────────────────────────────────────────
OPENING_ENABLED = True   # si existe VIDEO/opening.mp4 se reproduce al abrir el juego (X para saltar)
OPEN_FPS      = 30
STAR_SPEED    = 14     # Kirby: velocidad (px por frame) del luchador escupido como estrella
SUDDEN_DEATH_FRAMES = 75 * FPS   # VS CPU: si una ronda dura mas de 75 s, desaparecen las plataformas flotantes
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

# ── Audio ────────────────────────────────────────────────────
# Rutas RELATIVAS: se buscan dentro de la carpeta SFX que esta junto a este archivo.
SFX_DIR = os.path.join(BASE_DIR, "SFX")

def sfx(nombre):
    return os.path.join(SFX_DIR, nombre)

# Sonidos que ya tienes en la carpeta SFX:
AUDIO = {
    "music_menu"  : sfx("Super Smash Bros. Ultimate - Menu Theme.mp3"),
    "music_battle": sfx("Final Destination (stage) - Super Smash Bros. Ultimate.mp3"),
    "kirby_inhale": sfx("Kirby Inhale Sound Clip.mp3"),
    "explosion"   : sfx("Big Explosion Sound Effect.mp3"),
}

# El resto se busca SOLO en SFX/<nombre>.mp3 (o .wav / .ogg). Ejemplo: guarda un sonido
# de golpe como SFX/hit.mp3 y ya suena. Si el archivo no existe, ese sonido queda en silencio.
AUDIO_KEYS = ["hit", "ko", "kirby_jump", "kirby_hammer", "kirby_rock", "kirby_sword",
              "shockwave", "kris_save", "kris_slash", "kris_act", "gamer_phase", "gamer_missile",
              "menu_move", "menu_ok"]
for _k in AUDIO_KEYS:
    AUDIO[_k] = ""
    for _ext in (".mp3", ".wav", ".ogg"):
        if os.path.exists(sfx(_k + _ext)):
            AUDIO[_k] = sfx(_k + _ext)
            break

# Colores
C_BG         = (10,  10,  20)
C_PLATFORM   = (80,  60,  40)
C_PLATFORM_T = (120, 90,  55)
C_WHITE      = (255, 255, 255)
C_YELLOW     = (255, 215,   0)
C_RED        = (220,  50,  50)
C_GREEN      = ( 50, 220,  80)
C_CYAN       = (  0, 200, 255)
C_ORANGE     = (255, 130,  30)
C_GRAY       = (140, 140, 140)
C_DARK       = ( 30,  30,  45)
C_PINK       = (255, 100, 180)
C_FIRE       = (255,  80,   0)

K_LEFT   = pygame.K_LEFT
K_RIGHT  = pygame.K_RIGHT
K_UP     = pygame.K_UP
K_DOWN   = pygame.K_DOWN
K_ATTACK = pygame.K_z
K_JUMP   = pygame.K_UP
K_SPECIAL= pygame.K_x
K_COMMA  = pygame.K_COMMA   # Kirby: soltar la habilidad copiada

# ═══════════════════════ AUDIO MANAGER ═══════════════════════

class AudioManager:
    def __init__(self):
        self.sounds  = {}
        self.enabled = True
        self.sink    = None   # el host de multijugador anota aqui los sonidos para los demas
        self.music_key    = None    # cancion que esta sonando ahora
        self.music_offset = 0.0     # segundo desde el que empezo a sonar
        self.music_pos    = {}      # posicion (en segundos) donde se quedo cada cancion
        pygame.mixer.init()
        for key, path in AUDIO.items():
            if os.path.exists(path):
                try:
                    if key.startswith("music"):
                        pass  # musica se maneja aparte
                    else:
                        self.sounds[key] = pygame.mixer.Sound(path)
                except Exception as e:
                    print(f"[audio] No se pudo cargar {key}: {e}")
            else:
                if path and not path.startswith(r"C:\ruta"):
                    print(f"[audio] Archivo no encontrado: {path}")

    def play(self, key, volume=0.8):
        if not self.enabled:
            return
        if self.sink is not None and len(self.sink) < 24:
            self.sink.append(key)
        s = self.sounds.get(key)
        if s:
            s.set_volume(volume)
            s.play()

    def _remember_music_position(self):
        """Guarda en que segundo va la cancion actual (para poder seguir desde ahi despues)."""
        try:
            if self.music_key and pygame.mixer.music.get_busy():
                self.music_pos[self.music_key] = self.music_offset + pygame.mixer.music.get_pos() / 1000.0
        except Exception:
            pass

    def play_music(self, key, loop=True):
        """Pone una cancion.
        - Si esa MISMA cancion ya esta sonando, no hace nada (no se reinicia al cambiar de pantalla).
        - La musica del menu recuerda donde se quedo: despues de una pelea sigue desde ese punto."""
        path = AUDIO.get(key, "")
        if not os.path.exists(path):
            return
        try:
            if self.music_key == key and pygame.mixer.music.get_busy():
                return
            self._remember_music_position()
            start = self.music_pos.get(key, 0.0) if key == "music_menu" else 0.0
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(0.5)
            try:
                pygame.mixer.music.play(-1 if loop else 0, start=start)
            except Exception:
                pygame.mixer.music.play(-1 if loop else 0)        # posicion invalida: desde el principio
                start = 0.0
            self.music_key, self.music_offset = key, start
        except Exception as e:
            print(f"[audio] No se pudo reproducir musica {key}: {e}")

    def stop_music(self):
        self._remember_music_position()
        pygame.mixer.music.stop()
        self.music_key = None

AUDIO_MGR = None  # se inicializa en main()

# ═══════════════════════ HELPERS ═══════════════════════

def load_sprite(path, size=SPRITE_SIZE):
    ext = os.path.splitext(path)[1].lower()
    surf = None
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        try:
            img  = PILImage.open(path).convert("RGBA")
            img  = img.resize((size, size), PILImage.LANCZOS)
            surf = pygame.image.fromstring(img.tobytes(), (size, size), "RGBA")
        except Exception:
            surf = None
    if surf is None:
        surf = _placeholder(os.path.basename(path), size)
    return surf


def _placeholder(name, size):
    ext  = os.path.splitext(name)[1].lower() or "?"
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    color_map = {
        ".exe":(200,50,50), ".bat":(200,60,40), ".py":(70,130,200),
        ".js":(200,190,50), ".txt":(180,180,180), ".md":(160,160,200),
        ".zip":(160,100,200),".rar":(140,90,190), ".mp3":(80,200,120),
        ".wav":(60,190,110), ".mp4":(200,100,80), ".pdf":(200,80,80),
        ".docx":(80,100,200),
    }
    c = color_map.get(ext, (100,100,120))
    pygame.draw.rect(surf, c, (0,0,size,size), border_radius=8)
    pygame.draw.rect(surf, (255,255,255,60), (0,0,size,size), 2, border_radius=8)
    font = pygame.font.SysFont("consolas", max(9, size//5), bold=True)
    lbl  = font.render(ext[:5], True, (255,255,255))
    surf.blit(lbl, lbl.get_rect(center=(size//2, size//2)))
    return surf


def make_color_for(name):
    import colorsys
    h = hash(name) % 360
    r,g,b = colorsys.hsv_to_rgb(h/360, 0.85, 0.95)
    return (int(r*255), int(g*255), int(b*255))


# ═══════════════════════ PERSONAJES ═══════════════════════

def size_str(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{int(n)} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024.0


def file_profile(size):
    """Peso del archivo -> stats. t=0 (1 KB o menos): muy liviano ... t=1 (256 MB o mas): muy pesado.
       Mas pesado : mas lento, ataca mas lento, mas pesado (cuesta lanzarlo) y pega mas fuerte.
       Mas liviano: mas rapido, ataca rapido, facil de lanzar fuera del campo y pega menos."""
    size = max(1, int(size))
    t = min(1.0, max(0.0, (math.log2(size) - 10.0) / 18.0))
    return {"t": t,
            "weight": 0.7 + 0.8 * t,      # 0.70 .. 1.50
            "speed" : 1.3 - 0.55 * t,     # 1.30 .. 0.75
            "dmg"   : 0.75 + 0.6 * t,     # 0.75 .. 1.35
            "atk"   : 1.35 - 0.65 * t}    # velocidad de ataque: 1.35 (rapido) .. 0.70 (lento)


CHARACTERS = ["kirby", "none", "kris", "gamer64"]   # aqui se agregan mas en el futuro

# Estado que dura TODA la partida (torneo completo), guardado por archivo.
# Ej: las curaciones de Kris no se reinician entre rondas.
MATCH_STATE = {}


@lru_cache(maxsize=None)
def get_font(name, size, bold=False):
    """SysFont es lento: se crea una sola vez por (fuente, tamano)."""
    return pygame.font.SysFont(name, size, bold=bold)


class FakeKeys:
    """Teclas virtuales para que la IA use las habilidades (X + direccion)."""
    def __init__(self, *pressed):
        self.pressed = set(pressed)

    def __getitem__(self, key):
        return key in self.pressed


AI_INTENTS = [(), (K_DOWN,), (K_LEFT,), (K_RIGHT,), (K_UP,), (K_LEFT,), (K_RIGHT,)]


def draw_heart(surface, cx, cy, s, color):
    r = max(2, s // 2)
    pygame.draw.circle(surface, color, (cx - r // 2, cy - r // 3), r // 2 + 1)
    pygame.draw.circle(surface, color, (cx + r // 2, cy - r // 3), r // 2 + 1)
    pygame.draw.polygon(surface, color, [(cx - r, cy - 1), (cx + r, cy - 1), (cx, cy + r + 1)])


def draw_star(surface, cx, cy, r, color):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
    pygame.draw.polygon(surface, color, pts)


# Ayuda que se muestra en el menu al seleccionar un archivo
HAB_INFO = {
    "_ninguno": [
        "Haz clic en un archivo para ver su personaje y sus habilidades",
        "C: cambiar el personaje del archivo seleccionado",
        "Personajes: KIRBY / NONE / KRIS / GAMER64",
    ],
    "kirby": [
        "KIRBY - 7 saltos  |  Z: golpe",
        "X (quieto): Absorber a un luchador. Luego: X = escupirlo como estrella (1 s) | ↓ = tragarlo y copiar su X",
        "Con una habilidad copiada: la tecla , (coma) te devuelve a la normalidad",
        "X + ↓: Roca (inmune, aplasta, rompe con 400 dmg, 8s)",
        "X + ←/→: Martillo (mantener=carga/fuego, soltar=golpe)",
        "X + ↑: Espada ascendente (shockwave al aterrizar)",
    ],
    "none": [
        "NONE - 2 saltos  |  Z: golpe",
        "Sin habilidades especiales",
    ],
    "kris": [
        "KRIS - 2 saltos  |  Z: espada (combo de 3, el 3º lanza segun el daño)",
        "X (quieto): Save point (1º guarda, 2º vuelve + explosion, 50% de fallo)",
        "X + ↓: Down slash (rebota hasta 5 veces sobre enemigos)",
        "X + ←/→: Soul (paraliza 10s o hasta que Kris lo golpee)",
        "X + ↑: ACT (suelo: curarse, max 3 | aire: salto extra con slash)",
    ],
    "gamer64": [
        "GAMER64 - 2 saltos  |  Z: golpes  |  X (quieto): cambiar de fase (1 → 2 → 3)",
        "X + ↓: F1 carga diagonal | F2 misil al suelo (+boost) | F3 terremoto",
        "X + ←/→: F1 JARONA (cargar y soltar) | F2 misil teledirigido | F3 trampa glitch",
        "X + ↑: F1/F2 propulsion (1s) | F3 brazo corrupto (terremoto, mucho daño a ti)",
    ],
}


class SpecialBase:
    """Base comun de las habilidades especiales (X). Todo con valores por defecto."""
    jump_delay = 0      # frames de espera al saltar (Kris lo usa para distinguir ACT en el suelo)

    def __init__(self, owner):
        self.owner     = owner
        self.fx_list   = []
        self.fighters  = []
        self.platforms = []

    def input_locked(self):
        return False

    def blocks_jump(self):
        return False

    def skip_gravity(self):
        return False

    def grounded(self):
        """En el suelo de verdad. (Fighter.on_ground solo es True 1 de cada 3 frames
        cuando el luchador esta quieto, por eso se comprueba tambien la plataforma.)"""
        o = self.owner
        if o.on_ground:
            return True
        probe = o.rect.move(0, 2)
        return o.vy >= 0 and any(probe.colliderect(p) for p in self.platforms)

    def deactivate_special(self):
        """Llamado al SOLTAR X."""
        pass

    def update(self, fighters, platforms, keys_held, special_pressed, special_released):
        pass

    def draw(self, surface):
        pass

    # ── efectos visuales ─────────────────────────────────────
    def add_fx(self, x, y, r, color, life=18, kind="ring"):
        self.fx_list.append({"x": int(x), "y": int(y), "r": r, "life": life,
                             "max": life, "color": color, "kind": kind})

    def _update_fx(self):
        for e in self.fx_list[:]:
            e["life"] -= 1
            if e["life"] <= 0:
                self.fx_list.remove(e)

    def _draw_fx(self, surface):
        for e in self.fx_list:
            t     = 1 - e["life"] / e["max"]
            rad   = max(3, int(e["r"] * (0.3 + 0.7 * t)))
            alpha = max(0, int(220 * (1 - t)))
            s = pygame.Surface((rad * 2 + 6, rad * 2 + 6), pygame.SRCALPHA)
            c = (*e["color"], alpha)
            if e["kind"] == "flash":
                pygame.draw.circle(s, c, (rad + 3, rad + 3), rad)
            else:
                pygame.draw.circle(s, c, (rad + 3, rad + 3), rad, 3)
            surface.blit(s, (e["x"] - rad - 3, e["y"] - rad - 3))

    # ── daño ─────────────────────────────────────────────────
    def aoe(self, cx, cy, radius, power, launch=1.0):
        """Explosion: daña a los enemigos cerca de (cx, cy). No daña al dueño."""
        o = self.owner
        for other in self.fighters:
            if other is o or not other.alive:
                continue
            dx = other.rect.centerx - cx
            dy = other.rect.centery - cy
            if math.hypot(dx, dy) <= radius + SPRITE_SIZE / 2:
                other.receive_hit(power, 1 if dx >= 0 else -1, attacker=o, launch=launch)

    def quake(self, power, launch=0.7, self_damage=0):
        """Terremoto: daña a TODOS los enemigos y tambien al dueño (self_damage)."""
        o = self.owner
        for other in self.fighters:
            if other is o or not other.alive:
                continue
            d = 1 if other.rect.centerx >= o.rect.centerx else -1
            other.receive_hit(power, d, attacker=o, launch=launch)
        o.damage = min(o.damage + self_damage, MAX_DAMAGE)
        for r in (140, 260, 400):
            self.add_fx(o.rect.centerx, o.rect.bottom, r, C_ORANGE, 26)


class KirbyAbilities(SpecialBase):
    """
    Gestiona todas las habilidades especiales (X) de Kirby.
    Se instancia una vez por Fighter que tenga character='kirby'.
    """
    ROCK_DURATION    = 8 * FPS      # 8 segundos
    ROCK_BREAK_DMG   = 400
    HAMMER_FIRE_TIME = 90           # frames para fuego
    HAMMER_DANGER    = 150          # frames para empezar a perder vida
    SWORD_RISE_SPEED = -14
    SWORD_DURATION   = 40           # frames subiendo

    def __init__(self, owner):
        super().__init__(owner)

        # Estado roca
        self.is_rock       = False
        self.rock_timer    = 0
        self.rock_dmg_acc  = 0

        # Estado martillo
        self.hammering     = False
        self.hammer_charge = 0
        self.hammer_fired  = False
        self.hammer_is_fire= False

        # Estado espada
        self.sword_active  = False
        self.sword_timer   = 0
        self.sword_hit_ground = False   # para disparar shockwave

        # Absorcion
        self.inhaling      = False
        self.inhale_timer  = 0
        self.held          = None       # luchador que tiene absorbido
        self.held_t        = 0
        self.held_name     = None       # (para dibujar, tambien en los clientes online)
        self.held_color    = (255, 255, 255)
        self.ai_hold       = 0
        self.copy          = None       # habilidad X copiada (KrisAbilities / GamerAbilities)
        self.copy_kind     = None
        self.ai_copy_t     = 0
        self.no_ability_t  = 0
        self._prev_down    = False
        self._prev_comma   = False

        # Proyectiles activos de shockwave
        self.shockwaves    = []         # lista de {rect, vx, timer}

    # Con una habilidad copiada, Kirby se comporta como el otro personaje (solo en su X)
    @property
    def jump_delay(self):
        return self.copy.jump_delay if self.copy is not None else 0

    def input_locked(self):
        return self.copy.input_locked() if self.copy is not None else False

    def blocks_jump(self):
        return self.copy.blocks_jump() if self.copy is not None else False

    def skip_gravity(self):
        return self.copy.skip_gravity() if self.copy is not None else False

    # ─── ACTIVAR ESPECIAL (llamado al presionar X) ───────────
    def activate(self, keys):
        o = self.owner
        if o.knockback_timer > 4 or not o.alive:
            return
        if self.copy is not None:
            self.copy.activate(keys)
            return
        if self.held is not None:        # con un luchador absorbido, X escupe (se maneja en update)
            return

        # Si ya hay un estado activo, ignorar (excepto cargar martillo)
        if self.is_rock or self.sword_active:
            return

        moving_side = keys[K_LEFT] or keys[K_RIGHT]
        moving_down = keys[K_DOWN]
        moving_up   = keys[K_UP]

        if moving_down and not self.hammering:
            self._start_rock()
        elif moving_side and not self.hammering:
            self._start_hammer()
        elif moving_up and not self.hammering:
            self._start_sword()
        elif not moving_side and not moving_down and not moving_up:
            if not self.hammering:
                self._start_inhale()

    def deactivate_special(self):
        """Llamado al SOLTAR X (para el martillo)."""
        if self.copy is not None:
            self.copy.deactivate_special()
            return
        if self.hammering:
            self._fire_hammer()

    # ─── ROCA ────────────────────────────────────────────────
    def _start_rock(self):
        o = self.owner
        self.is_rock     = True
        self.rock_timer  = self.ROCK_DURATION
        self.rock_dmg_acc= 0
        o.vx = 0
        o.vy = 6   # caida rapida
        AUDIO_MGR.play("kirby_rock")

    def _update_rock(self, fighters, platforms):
        o = self.owner
        self.rock_timer -= 1
        o.vy = min(o.vy + 1.5, 18)   # caida rapida con gravedad extra

        # Aplastar enemigos debajo
        rock_hit = o.rect.inflate(-4, 4)
        for other in fighters:
            if other is o or not other.alive:
                continue
            if rock_hit.colliderect(other.rect) and o.vy > 0:
                direction = 1 if other.rect.centerx > o.rect.centerx else -1
                other.receive_hit(o.atk_power * 1.5, direction)
                AUDIO_MGR.play("hit")

        # Romper por tiempo o daño acumulado
        if self.rock_timer <= 0 or self.rock_dmg_acc >= self.ROCK_BREAK_DMG:
            self.is_rock = False

    def rock_absorb_damage(self, dmg):
        if self.is_rock:
            self.rock_dmg_acc += dmg
            return True   # daño bloqueado
        return False

    # ─── MARTILLO ────────────────────────────────────────────
    def _start_hammer(self):
        self.hammering     = True
        self.hammer_charge = 0
        self.hammer_fired  = False
        self.hammer_is_fire= False
        AUDIO_MGR.play("kirby_hammer")

    def _update_hammer(self, fighters):
        o = self.owner
        if not self.hammering:
            return
        self.hammer_charge += 1

        # Cargar -> fuego
        if self.hammer_charge >= self.HAMMER_FIRE_TIME:
            self.hammer_is_fire = True

        # Cargar demasiado -> perder vida
        if self.hammer_charge >= self.HAMMER_DANGER:
            if self.hammer_charge % 20 == 0:
                o.damage = min(o.damage + 5, MAX_DAMAGE)

    def _fire_hammer(self):
        o = self.owner
        if not self.hammering:
            return
        self.hammering = False

        # Hitbox del martillo al soltar
        power = o.atk_power * (2.2 if self.hammer_is_fire else 1.4)
        hb = pygame.Rect(
            o.rect.centerx if o.facing == 1 else o.rect.left - ATTACK_RANGE,
            o.rect.top, ATTACK_RANGE, o.rect.h
        )
        self.hammer_fired  = True
        self.hammer_charge = 0
        self.hammer_is_fire= False
        AUDIO_MGR.play("hit")
        return hb, power   # devuelve para aplicar en update

    def get_hammer_hitbox_and_power(self):
        if self.hammer_fired:
            self.hammer_fired = False
            o = self.owner
            power = o.atk_power * 1.4
            hb = pygame.Rect(
                o.rect.centerx if o.facing==1 else o.rect.left-ATTACK_RANGE,
                o.rect.top, ATTACK_RANGE, o.rect.h
            )
            return hb, power
        return None, 0

    # ─── ESPADA (UP+X) ───────────────────────────────────────
    def _start_sword(self):
        o = self.owner
        self.sword_active = True
        self.sword_timer  = self.SWORD_DURATION
        self.sword_hit_ground = False
        o.vy = self.SWORD_RISE_SPEED
        o.jump_count = o.MAX_JUMPS   # consume todos los saltos
        AUDIO_MGR.play("kirby_sword")

    def _update_sword(self, fighters, platforms):
        o = self.owner
        if not self.sword_active:
            return
        self.sword_timer -= 1

        # Hitbox de la espada (arco hacia arriba)
        sword_hb = pygame.Rect(
            o.rect.x - 10, o.rect.top - 30, o.rect.w + 20, 35
        )
        for other in fighters:
            if other is o or not other.alive:
                continue
            if sword_hb.colliderect(other.rect):
                direction = 1 if other.rect.centerx > o.rect.centerx else -1
                other.receive_hit(o.atk_power * 1.6, direction)
                AUDIO_MGR.play("hit")

        # Termina cuando se acaba el timer o toca suelo al caer
        if self.sword_timer <= 0:
            self.sword_active = False

        if o.on_ground and self.sword_timer < self.SWORD_DURATION - 10:
            self.sword_active = False
            # Shockwave si aterrizo en plataforma
            self._spawn_shockwave()
            AUDIO_MGR.play("shockwave")

    def _spawn_shockwave(self):
        o = self.owner
        for direction in (-1, 1):
            self.shockwaves.append({
                "rect" : pygame.Rect(o.rect.centerx-8, o.rect.bottom-12, 16, 12),
                "vx"   : direction * 5,
                "timer": 45,
                "power": o.atk_power * 0.8,
            })

    def _update_shockwaves(self, fighters):
        for sw in self.shockwaves[:]:
            sw["timer"] -= 1
            sw["rect"].x += int(sw["vx"])
            if sw["timer"] <= 0:
                self.shockwaves.remove(sw)
                continue
            for other in fighters:
                if other is self.owner or not other.alive:
                    continue
                if sw["rect"].colliderect(other.rect):
                    direction = 1 if sw["vx"] > 0 else -1
                    other.receive_hit(sw["power"], direction)
                    AUDIO_MGR.play("hit")
                    self.shockwaves.remove(sw)
                    break

    # ─── INHALAR / ABSORBER ──────────────────────────────────
    INHALE_FRAMES = 45
    INHALE_RANGE  = 150

    def _start_inhale(self):
        if self.held is not None or self.copy is not None:
            return
        self.inhaling     = True
        self.inhale_timer = self.INHALE_FRAMES
        AUDIO_MGR.play("kirby_inhale")

    def _update_inhale(self, fighters):
        """Atrae a los luchadores de enfrente; el primero que toca la boca queda absorbido."""
        o = self.owner
        self.inhale_timer -= 1
        zone = pygame.Rect(o.rect.centerx if o.facing == 1 else o.rect.centerx - self.INHALE_RANGE,
                           o.rect.top - 20, self.INHALE_RANGE, o.rect.h + 40)
        mouth = o.rect.inflate(26, 8)
        for other in fighters:
            if other is o or not other.alive or other.captured or other.is_rock():
                continue
            if mouth.colliderect(other.rect):
                self._capture(other)
                return
            if zone.colliderect(other.rect):               # tira de el hacia la boca
                other.rect.x += 3 if o.rect.centerx > other.rect.centerx else -3
        if self.inhale_timer <= 0:
            self.inhaling = False

    def _capture(self, v):
        o = self.owner
        if v.special:
            v.special.__init__(v)                          # cancela lo que estuviera haciendo
        v.atk_active = False
        v.captured, v.captor = "held", o
        v.vx = v.vy = 0
        self.held, self.held_t = v, 0
        self.held_name, self.held_color = v.name, v.color
        self.ai_hold = random.randint(25, 70)
        self.inhaling = False
        AUDIO_MGR.play("kirby_inhale")

    def _clear_held(self):
        self.held = None
        self.held_name = None

    def _update_held(self, special_pressed, down_now, down_edge, human):
        o, v = self.owner, self.held
        if v is None or not v.alive or v.captor is not o or v.captured != "held":
            self._clear_held()
            return
        self.held_t += 1
        v.rect.center = o.rect.center
        v.vx = v.vy = 0
        if special_pressed:
            if down_now:
                self._swallow()                             # X con ↓ tambien traga
            else:
                self._spit()
        elif down_edge:
            self._swallow()                                 # ↓ = tragar y copiar
        elif human:
            if self.held_t >= 10 * FPS:                     # nadie lo suelta: se escupe solo
                self._spit()
        else:
            self.ai_hold -= 1
            if self.ai_hold <= 0:
                if v.character in ("kris", "gamer64") and random.random() < 0.45:
                    self._swallow()
                else:
                    self._spit()

    def _spit(self):
        """Escupirlo: sale disparado como estrella durante 1 segundo (o hasta golpear a alguien)."""
        o, v = self.owner, self.held
        if v is None:
            return
        self._clear_held()
        v.captured, v.captor = "star", o
        v.star_t, v.star_dir, v.star_power = FPS, o.facing, o.atk_power * 1.3
        v.rect.center = (o.rect.centerx + o.facing * (o.rect.w // 2 + v.rect.w // 2 + 2), o.rect.centery)
        v.vx = v.vy = 0
        AUDIO_MGR.play("shockwave")

    def _swallow(self):
        """Tragarlo: Kirby copia la habilidad X del otro. Solo la suelta con la tecla , (coma)."""
        o, v = self.owner, self.held
        if v is None:
            return
        self._clear_held()
        new_copy = None
        if v.character == "kris":
            new_copy = KrisAbilities(o)
        elif v.character == "gamer64":
            new_copy = GamerAbilities(o)
        v.release_captured(stun=18)                         # el rival sale sin daño
        v.rect.center = (o.rect.centerx + o.facing * 40, o.rect.centery)
        v.vx, v.vy = o.facing * 3, -5.0
        if new_copy is not None:
            self.copy, self.copy_kind = new_copy, v.character
            self.ai_copy_t = 12 * FPS
            self.add_fx(o.rect.centerx, o.rect.centery, 60, C_PINK, 22, "flash")
            AUDIO_MGR.play("kris_save")
        else:
            self.no_ability_t = 60                          # el rival no tenia habilidad X que copiar

    def _drop_copy(self):
        o = self.owner
        self.copy, self.copy_kind = None, None
        self.add_fx(o.rect.centerx, o.rect.centery, 50, C_WHITE, 18)

    # ─── UPDATE GENERAL ──────────────────────────────────────
    def update(self, fighters, platforms, keys_held, special_pressed, special_released):
        o = self.owner
        human = o.is_player or o.remote
        down_now   = bool(keys_held[K_DOWN])
        comma_now  = bool(keys_held[K_COMMA])
        down_edge  = down_now and not self._prev_down
        comma_edge = comma_now and not self._prev_comma
        self._prev_down, self._prev_comma = down_now, comma_now
        if self.no_ability_t > 0:
            self.no_ability_t -= 1
        self._update_fx()

        # Habilidad copiada: la X es la del otro personaje; la coma la suelta
        if self.copy is not None:
            self.ai_copy_t -= 1
            if comma_edge or (not human and self.ai_copy_t <= 0):
                self._drop_copy()
            else:
                self.copy.update(fighters, platforms, keys_held, special_pressed, special_released)
                self._update_shockwaves(fighters)
                return

        # Luchador absorbido: X lo escupe, ↓ lo traga
        if self.held is not None:
            self._update_held(special_pressed, down_now, down_edge, human)
            self._update_shockwaves(fighters)
            return
        elif self.held_name:
            self.held_name = None

        if special_pressed:
            self.activate(keys_held)
        if special_released:
            self.deactivate_special()

        if self.is_rock:
            self._update_rock(fighters, platforms)
        if self.hammering:
            self._update_hammer(fighters)
        if self.sword_active:
            self._update_sword(fighters, platforms)
        if self.inhaling:
            self._update_inhale(fighters)
        self._update_shockwaves(fighters)

    # ─── DIBUJAR EFECTOS ESPECIALES ──────────────────────────
    def draw(self, surface):
        o = self.owner

        if self.is_rock:
            # Overlay gris encima del sprite
            rock_surf = pygame.Surface((o.rect.w, o.rect.h), pygame.SRCALPHA)
            pygame.draw.ellipse(rock_surf, (160,160,160,200),
                                (0,0,o.rect.w, o.rect.h))
            surface.blit(rock_surf, o.rect.topleft)
            # Barra de resistencia de roca
            pct = 1 - (self.rock_dmg_acc / self.ROCK_BREAK_DMG)
            bw  = o.rect.w
            pygame.draw.rect(surface, (80,80,80),
                             (o.rect.x, o.rect.top-8, bw, 5), border_radius=2)
            pygame.draw.rect(surface, (200,200,200),
                             (o.rect.x, o.rect.top-8, int(bw*pct), 5), border_radius=2)

        if self.hammering:
            # Dibujar martillo
            hx = o.rect.right if o.facing==1 else o.rect.left-14
            col = C_FIRE if self.hammer_is_fire else (150,80,30)
            pygame.draw.rect(surface, col, (hx, o.rect.top, 14, 30), border_radius=4)
            # Barra de carga
            charge_pct = min(self.hammer_charge / self.HAMMER_DANGER, 1.0)
            pygame.draw.rect(surface, (50,50,50),
                             (o.rect.x, o.rect.top-8, o.rect.w, 5), border_radius=2)
            bar_col = C_FIRE if charge_pct > 0.6 else C_YELLOW
            pygame.draw.rect(surface, bar_col,
                             (o.rect.x, o.rect.top-8,
                              int(o.rect.w * charge_pct), 5), border_radius=2)

        if self.sword_active:
            # Destello de espada
            sx = o.rect.centerx
            sy = o.rect.top - 20
            pygame.draw.line(surface, C_CYAN,
                             (sx, sy), (sx + o.facing*30, sy-30), 3)
            pygame.draw.line(surface, C_WHITE,
                             (sx, sy), (sx + o.facing*20, sy-20), 1)

        if self.inhaling:
            # Particulas siendo atraidas
            cx, cy = o.rect.centerx, o.rect.centery
            fx = cx + o.facing*40
            for _ in range(4):
                px = fx + random.randint(-20,20)
                py = cy + random.randint(-15,15)
                pygame.draw.circle(surface, C_PINK, (px,py), 3)

        # Shockwaves
        for sw in self.shockwaves:
            s = pygame.Surface((sw["rect"].w+20, sw["rect"].h+10), pygame.SRCALPHA)
            pygame.draw.ellipse(s, (*C_CYAN, 160), s.get_rect())
            surface.blit(s, (sw["rect"].x-10, sw["rect"].y-5))

        # Luchador absorbido (se ve el bulto en la boca) y pistas de los controles
        if self.held_name:
            bx, by = o.rect.centerx + o.facing * 12, o.rect.centery
            pygame.draw.circle(surface, self.held_color, (bx, by), 13)
            pygame.draw.circle(surface, C_WHITE, (bx, by), 13, 2)
            tip = get_font("consolas", 10, True).render("X: escupir   ↓: tragar", True, C_WHITE)
            surface.blit(tip, (o.rect.centerx - tip.get_width() // 2, o.rect.top - 34))

        # Habilidad copiada
        if self.copy is not None:
            self.copy.draw(surface)
            tip = get_font("consolas", 10, True).render(
                f"COPIA: {(self.copy_kind or '').upper()}   ( , ) = soltar", True, C_PINK)
            surface.blit(tip, (o.rect.centerx - tip.get_width() // 2, o.rect.top - 46))
        if self.no_ability_t > 0:
            tip = get_font("consolas", 10, True).render("sin habilidad X que copiar", True, C_GRAY)
            surface.blit(tip, (o.rect.centerx - tip.get_width() // 2, o.rect.top - 34))
        self._draw_fx(surface)


# ═══════════════════════ KRIS ═══════════════════════

class KrisAbilities(SpecialBase):
    """
    Kris. Z = espada con combo de 3 (la logica esta en Fighter.try_attack).
      X (quieto)   : Save point (1er toque guarda, 2do vuelve + mini explosion; 50% falla)
      X + abajo    : Down slash (rebota hasta 5 veces sobre enemigos)
      X + lados    : Soul (paraliza 10 s o hasta que Kris lo golpee)
      X + arriba   : ACT (suelo: curarse, max 3 por partida | aire: salto extra con slash)
    """
    jump_delay        = 7          # pequeña espera al saltar para poder hacer ACT en el suelo (↑ + X)
    HEALS_MAX         = 3
    HEAL_AMOUNT       = 45
    HEAL_FRAMES       = 30
    PARALYSIS_FRAMES  = 10 * FPS
    SAVE_FAIL_CHANCE  = 0.5
    SLASH_SPEED       = 15
    SLASH_MAX_BOUNCES = 5
    BOUNCE_VY         = -11
    BOUNCE_RISE       = 16

    def __init__(self, owner):
        super().__init__(owner)
        # Save point
        self.save_pos = None
        self.save_t   = 0
        self.fail_t   = 0
        # Down slash
        self.slash_active = False
        self.slash_timer  = 0
        self.dive_delay   = 0
        self.bounces      = 0
        self.bounce_lock  = {}
        # Soul
        self.souls   = []
        self.soul_cd = 0
        # ACT
        self.acting         = 0
        self.act_label      = 0
        self.heal_rate      = 0.0
        self.heal_acc       = 0.0
        self.up_slash_timer = 0
        self.up_hit         = set()
        self.air_act_used   = False

    @property
    def heals_left(self):
        net = self.__dict__.get("_net_heals")           # en los clientes viene del host
        if net is not None:
            return net
        used = MATCH_STATE.get(self.owner.path, {}).get("heals", 0)
        return max(0, self.HEALS_MAX - used)

    def input_locked(self):
        return self.acting > 0

    def blocks_jump(self):
        return self.slash_active or self.acting > 0

    # ─── ACTIVAR ESPECIAL (al presionar X) ───────────────────
    def activate(self, keys):
        o = self.owner
        if o.knockback_timer > 4 or not o.alive:
            return
        if self.slash_active or self.acting > 0 or self.up_slash_timer > 0:
            return
        if keys[K_DOWN]:
            self._start_slash()
        elif keys[K_LEFT] or keys[K_RIGHT]:
            self._throw_soul()
        elif keys[K_UP]:
            self._act()
        else:
            self._save_point()

    # ─── SAVE POINT ──────────────────────────────────────────
    def _save_point(self):
        o = self.owner
        if self.save_pos is None:
            self.save_pos = (o.rect.centerx, o.rect.bottom)
            self.add_fx(o.rect.centerx, o.rect.bottom - 12, 32, C_YELLOW, 18)
            AUDIO_MGR.play("kris_save")
            return
        sx, sy = self.save_pos
        self.save_pos = None
        if random.random() < self.SAVE_FAIL_CHANCE:
            # Fallo: el save desaparece y no hay teletransporte
            self.fail_t = 40
            self.add_fx(sx, sy - 12, 30, C_RED, 18)
            return
        o.rect.midbottom = (sx, sy)
        o.vx = o.vy = 0
        self.add_fx(o.rect.centerx, o.rect.centery, 85, C_YELLOW, 22, "flash")
        self.add_fx(o.rect.centerx, o.rect.centery, 85, C_WHITE, 22)
        self.aoe(o.rect.centerx, o.rect.centery, 85, o.atk_power * 1.0, launch=1.0)
        AUDIO_MGR.play("explosion")

    # ─── DOWN SLASH ──────────────────────────────────────────
    def _start_slash(self):
        o = self.owner
        self.slash_active = True
        self.slash_timer  = 240
        self.bounces      = 0
        self.bounce_lock  = {}
        if self.grounded():
            o.vy = -9               # pequeño salto antes de clavar la espada
            o.on_ground = False
            self.dive_delay = 10
        else:
            self.dive_delay = 0
            o.vy = self.SLASH_SPEED
        AUDIO_MGR.play("kris_slash")

    def _update_slash(self):
        o = self.owner
        self.slash_timer -= 1
        for k in list(self.bounce_lock):
            self.bounce_lock[k] -= 1
            if self.bounce_lock[k] <= 0:
                del self.bounce_lock[k]

        if self.dive_delay > 0:
            self.dive_delay -= 1
            if self.dive_delay == 0:
                o.vy = self.SLASH_SPEED
        else:
            o.vy = max(o.vy, self.SLASH_SPEED)
            if self.bounces < self.SLASH_MAX_BOUNCES:
                hb = pygame.Rect(o.rect.x - 4, o.rect.bottom - 8, o.rect.w + 8, 28)
                for other in self.fighters:
                    if other is o or not other.alive:
                        continue
                    if self.bounce_lock.get(id(other), 0) > 0:
                        continue
                    if hb.colliderect(other.rect):
                        d = 1 if other.rect.centerx >= o.rect.centerx else -1
                        other.receive_hit(o.atk_power * 0.9, d, attacker=o, launch=0.35)
                        self.bounces += 1
                        self.bounce_lock[id(other)] = 12
                        o.vy = self.BOUNCE_VY            # rebote
                        self.dive_delay = self.BOUNCE_RISE
                        o.rect.bottom = min(o.rect.bottom, other.rect.top + 4)
                        self.add_fx(o.rect.centerx, o.rect.bottom, 34, C_CYAN, 14)
                        AUDIO_MGR.play("hit")
                        break

        # Termina al tocar el suelo (tras 5 rebotes cae directo) o por seguridad
        if (o.on_ground and self.dive_delay == 0) or self.slash_timer <= 0:
            self.slash_active = False
            self.add_fx(o.rect.centerx, o.rect.bottom, 30, C_WHITE, 12)

    # ─── SOUL ────────────────────────────────────────────────
    def _throw_soul(self):
        o = self.owner
        if self.soul_cd > 0 or self.souls:
            return
        self.souls.append({
            "rect" : pygame.Rect(o.rect.centerx - 9, o.rect.centery - 9, 18, 18),
            "vx"   : o.facing * 7,
            "timer": 70,
        })
        self.soul_cd = 45
        AUDIO_MGR.play("kris_act")

    def _update_souls(self):
        o = self.owner
        for s in self.souls[:]:
            s["timer"] -= 1
            s["rect"].x += int(s["vx"])
            if s["timer"] <= 0 or s["rect"].right < -50 or s["rect"].left > WIN_W + 50:
                self.souls.remove(s)
                continue
            for other in self.fighters:
                if other is o or not other.alive:
                    continue
                if s["rect"].colliderect(other.rect):
                    other.paralyzed    = self.PARALYSIS_FRAMES
                    other.paralyzed_by = o
                    other.vx = 0
                    self.add_fx(other.rect.centerx, other.rect.centery, 42, (255, 60, 90), 20, "flash")
                    AUDIO_MGR.play("hit")
                    self.souls.remove(s)
                    break

    # ─── ACT ─────────────────────────────────────────────────
    def _act(self):
        o = self.owner
        o.jump_buffer = 0                  # cancela el salto pendiente de la tecla ↑
        AUDIO_MGR.play("kris_act")
        if self.grounded():
            # En el suelo: curacion rapida (max 3 por partida)
            self.act_label = 30
            if self.heals_left > 0 and o.damage > 0:
                MATCH_STATE.setdefault(o.path, {"heals": 0})["heals"] += 1
                self.acting    = self.HEAL_FRAMES
                self.heal_rate = self.HEAL_AMOUNT / self.HEAL_FRAMES
                self.heal_acc  = 0.0
                self.add_fx(o.rect.centerx, o.rect.centery, 50, C_GREEN, 30, "flash")
            else:
                self.acting    = 12        # pose sin efecto (sin curaciones o sin daño)
                self.heal_rate = 0.0
        elif not self.air_act_used:
            # En el aire: salto extra con slash hacia arriba, y luego cae
            self.air_act_used   = True
            self.up_slash_timer = 16
            self.up_hit         = set()
            o.vy = -12
            o.on_ground = False
            self.add_fx(o.rect.centerx, o.rect.top, 40, C_CYAN, 14)
            AUDIO_MGR.play("kris_slash")

    def _update_up_slash(self):
        o = self.owner
        self.up_slash_timer -= 1
        hb = pygame.Rect(o.rect.x - 8, o.rect.top - 36, o.rect.w + 16, 44)
        for other in self.fighters:
            if other is o or not other.alive or id(other) in self.up_hit:
                continue
            if hb.colliderect(other.rect):
                self.up_hit.add(id(other))
                d = 1 if other.rect.centerx >= o.rect.centerx else -1
                other.receive_hit(o.atk_power * 1.2, d, attacker=o, launch=1.0)
                AUDIO_MGR.play("hit")

    # ─── UPDATE / DRAW ───────────────────────────────────────
    def update(self, fighters, platforms, keys_held, special_pressed, special_released):
        o = self.owner
        self.fighters, self.platforms = fighters, platforms
        if self.grounded():
            self.air_act_used = False
        if self.soul_cd > 0:
            self.soul_cd -= 1
        if self.act_label > 0:
            self.act_label -= 1
        if self.fail_t > 0:
            self.fail_t -= 1

        if special_pressed:
            self.activate(keys_held)

        if self.acting > 0:
            self.acting -= 1
            o.vx = 0
            if self.heal_rate > 0:
                self.heal_acc += self.heal_rate
                n = int(self.heal_acc)
                self.heal_acc -= n
                o.damage = max(0, o.damage - n)
        if self.slash_active:
            self._update_slash()
        if self.up_slash_timer > 0:
            self._update_up_slash()
        self._update_souls()
        self._update_fx()

    def draw(self, surface):
        o = self.owner
        self.save_t += 1

        # Save point: estrella amarilla
        if self.save_pos:
            sx, sy = self.save_pos
            bob = int(math.sin(self.save_t * 0.15) * 3)
            draw_star(surface, sx, sy - 16 + bob, 11, C_YELLOW)
            draw_star(surface, sx, sy - 16 + bob, 5, C_WHITE)

        # Down slash: espada hacia abajo
        if self.slash_active:
            cx = o.rect.centerx
            pygame.draw.line(surface, (210, 235, 255), (cx, o.rect.bottom - 6), (cx, o.rect.bottom + 26), 4)
            pygame.draw.line(surface, C_CYAN, (cx - 8, o.rect.bottom - 6), (cx + 8, o.rect.bottom - 6), 3)

        # Slash hacia arriba (ACT en el aire)
        if self.up_slash_timer > 0:
            cx = o.rect.centerx
            for i in range(3):
                pygame.draw.arc(surface, C_CYAN,
                                (cx - 26 - i * 4, o.rect.top - 40 - i * 3, 52 + i * 8, 50),
                                0.3, math.pi - 0.3, 2)

        # Soul: corazon rojo
        for s in self.souls:
            draw_heart(surface, s["rect"].centerx, s["rect"].centery, 20, (255, 40, 70))
            draw_heart(surface, s["rect"].centerx, s["rect"].centery, 8, (255, 160, 170))

        # Texto de ACT / fallo del save
        if self.act_label > 0 or self.acting > 0:
            lbl = get_font("consolas", 12, True).render("ACT", True, C_YELLOW)
            surface.blit(lbl, (o.rect.centerx - lbl.get_width() // 2, o.rect.top - 34))
        if self.fail_t > 0:
            lbl = get_font("consolas", 12, True).render("FAIL", True, C_RED)
            surface.blit(lbl, (o.rect.centerx - lbl.get_width() // 2, o.rect.top - 34))

        # Curaciones restantes
        hl = get_font("consolas", 9, True).render(f"+{self.heals_left}", True, C_GREEN)
        surface.blit(hl, (o.rect.x + 34, o.rect.bottom + 1))

        self._draw_fx(surface)


# ═══════════════════════ GAMER64 ═══════════════════════

class GamerAbilities(SpecialBase):
    """
    Gamer64: 3 fases (X quieto cambia de fase).
      X + abajo : F1 carga diagonal | F2 misil al suelo (+boost) | F3 golpe al suelo (terremoto)
      X + lados : F1 JARONA (cargar y soltar) | F2 misil teledirigido | F3 trampa glitch (2 usos)
      X + arriba: F1/F2 propulsion 1 s | F3 brazo corrupto (terremoto, mucho daño a ti)
    """
    PHASE_COLORS = {1: (0, 200, 255), 2: (255, 130, 30), 3: (255, 0, 200)}
    PHASE_NAMES  = {1: "FASE 1", 2: "FASE 2", 3: "FASE 3"}
    CHARGE_MAX   = 150           # frames maximos de carga de la JARONA
    PROP_FRAMES  = 60            # 1 segundo de propulsion

    def __init__(self, owner):
        super().__init__(owner)
        self.phase      = 1
        self.phase_cd   = 0
        self.missile_cd = 0
        # F1 abajo: carga diagonal
        self.diag       = False
        self.diag_dir   = 1
        self.diag_delay = 0
        self.diag_timer = 0
        self.diag_hit   = set()
        # F3 abajo: golpe al suelo
        self.slam       = False
        self.slam_delay = 0
        self.slam_timer = 0
        # F1 lados: JARONA
        self.charging   = False
        self.charge     = 0
        self.dash_timer = 0
        self.dash_speed = 0.0
        self.dash_power = 1.0
        self.dash_hit   = set()
        # Propulsion
        self.prop_timer = 0
        self.prop_used  = False
        # F3 arriba: brazo corrupto
        self.arm_state  = None
        self.arm_timer  = 0
        self.arm_total  = 0
        # Proyectiles y trampa
        self.missiles   = []
        self.trap       = None

    # ─── ESTADOS ─────────────────────────────────────────────
    def busy(self):
        return (self.diag or self.slam or self.charging or self.dash_timer > 0
                or self.prop_timer > 0 or self.arm_state is not None)

    def input_locked(self):
        return (self.diag or self.slam or self.charging or self.dash_timer > 0
                or self.arm_state is not None)

    def blocks_jump(self):
        return self.busy()

    def skip_gravity(self):
        return self.charging or self.dash_timer > 0 or self.prop_timer > 0

    # ─── ACTIVAR ESPECIAL (al presionar X) ───────────────────
    def activate(self, keys):
        o = self.owner
        if o.knockback_timer > 4 or not o.alive:
            return
        if self.busy():
            return
        if keys[K_DOWN]:
            self._down()
        elif keys[K_LEFT] or keys[K_RIGHT]:
            self._side()
        elif keys[K_UP]:
            self._up()
        else:
            self._change_phase()

    def deactivate_special(self):
        """Soltar X: dispara la JARONA cargada."""
        if self.charging:
            self._fire_charge()

    def _change_phase(self):
        if self.phase_cd > 0:
            return
        o = self.owner
        self.phase    = self.phase % 3 + 1
        self.phase_cd = 20
        col = self.PHASE_COLORS[self.phase]
        self.add_fx(o.rect.centerx, o.rect.centery, 55, col, 20, "flash")
        self.add_fx(o.rect.centerx, o.rect.centery, 85, col, 24)
        AUDIO_MGR.play("gamer_phase")

    # ─── X + ABAJO ───────────────────────────────────────────
    def _down(self):
        o = self.owner
        if self.phase == 1:
            self.diag       = True
            self.diag_dir   = o.facing
            self.diag_timer = 120
            self.diag_hit   = set()
            if self.grounded():
                o.vy = -9
                o.on_ground = False
                self.diag_delay = 8
            else:
                self.diag_delay = 0
                o.vy = 13
        elif self.phase == 2:
            if self.missile_cd > 0:
                return
            self.missile_cd = 30
            self.missiles.append({
                "kind": "down", "x": float(o.rect.centerx), "y": float(o.rect.bottom - 2),
                "vx": o.facing * 2.5, "vy": 8.0, "life": 120,
                "rect": pygame.Rect(0, 0, 10, 16),
            })
            AUDIO_MGR.play("gamer_missile")
        else:
            self.slam       = True
            self.slam_timer = 120
            if self.grounded():
                o.vy = -10
                o.on_ground = False
                self.slam_delay = 10
            else:
                self.slam_delay = 0
                o.vy = 18

    def _update_diag(self):
        o = self.owner
        self.diag_timer -= 1
        if self.diag_delay > 0:
            self.diag_delay -= 1
            o.vx = self.diag_dir * 3
            return
        o.vx = self.diag_dir * 9
        o.vy = max(o.vy, 13)
        for other in self.fighters:
            if other is o or not other.alive or id(other) in self.diag_hit:
                continue
            if o.rect.colliderect(other.rect):
                self.diag_hit.add(id(other))
                other.receive_hit(o.atk_power * 0.9, self.diag_dir, attacker=o, launch=0.8)
                AUDIO_MGR.play("hit")
        if o.on_ground or self.diag_timer <= 0:
            self.diag = False
            o.vx = 0
            # Mini impacto al golpear el suelo
            self.aoe(o.rect.centerx, o.rect.bottom, 75, o.atk_power * 1.0, launch=1.0)
            self.add_fx(o.rect.centerx, o.rect.bottom, 80, C_CYAN, 18)
            self.add_fx(o.rect.centerx, o.rect.bottom, 50, C_WHITE, 14, "flash")
            AUDIO_MGR.play("shockwave")

    def _update_slam(self):
        o = self.owner
        self.slam_timer -= 1
        o.vx = 0
        if self.slam_delay > 0:
            self.slam_delay -= 1
            return
        o.vy = max(o.vy, 18)
        if o.on_ground or self.slam_timer <= 0:
            self.slam = False
            # Terremoto leve: daña a todos, incluido Gamer
            self.quake(o.atk_power * 0.9, launch=0.7, self_damage=6)
            AUDIO_MGR.play("shockwave")

    # ─── X + LADOS ───────────────────────────────────────────
    def _side(self):
        o = self.owner
        if self.phase == 1:
            # JARONA: se congela cargando (vulnerable); se dispara al soltar X
            self.charging = True
            self.charge   = 0
            o.vx = 0
            o.vy = 0
        elif self.phase == 2:
            if self.missile_cd > 0:
                return
            self.missile_cd = 30
            self.missiles.append({
                "kind": "homing", "x": float(o.rect.centerx + o.facing * 20), "y": float(o.rect.centery),
                "vx": o.facing * 5.0, "vy": -1.5, "life": 150,
                "rect": pygame.Rect(0, 0, 14, 10),
            })
            AUDIO_MGR.play("gamer_missile")
        else:
            if self.trap is None:
                # 1er uso: deja la trampa glitch en el suelo
                self.trap = {"x": o.rect.centerx, "y": float(o.rect.bottom), "vy": 0.0, "landed": False}
                self.add_fx(o.rect.centerx, o.rect.bottom, 30, C_PINK, 14)
            else:
                # 2do uso: explota
                t = self.trap
                self.trap = None
                cx, cy = t["x"], t["y"] - 10
                self.aoe(cx, cy, 110, o.atk_power * 1.3, launch=1.1)
                self.add_fx(cx, cy, 120, (255, 0, 200), 24, "flash")
                self.add_fx(cx, cy, 150, (0, 255, 200), 26)
                AUDIO_MGR.play("explosion")

    def _update_charge(self):
        o = self.owner
        if o.knockback_timer > 0:            # un golpe interrumpe la carga
            self.charging = False
            self.charge   = 0
            return
        self.charge += 1
        o.vx = 0
        o.vy = 0
        if self.charge >= self.CHARGE_MAX:
            self._fire_charge()

    def _fire_charge(self):
        frac = min(self.charge / 120.0, 1.0)     # mas carga = mas lejos
        self.charging   = False
        self.dash_speed = 9 + 11 * frac
        self.dash_timer = 8 + int(22 * frac)
        self.dash_power = 1.0 + 1.0 * frac
        self.dash_hit   = set()
        self.charge     = 0
        AUDIO_MGR.play("shockwave")

    def _update_dash(self):
        o = self.owner
        self.dash_timer -= 1
        o.vx = o.facing * self.dash_speed
        o.vy = 0
        for other in self.fighters:
            if other is o or not other.alive or id(other) in self.dash_hit:
                continue
            if o.rect.inflate(16, 6).colliderect(other.rect):
                self.dash_hit.add(id(other))
                other.receive_hit(o.atk_power * self.dash_power, o.facing, attacker=o,
                                  launch=0.8 + 0.4 * (self.dash_power - 1.0))
                self.add_fx(other.rect.centerx, other.rect.centery, 36, C_CYAN, 12, "flash")
                AUDIO_MGR.play("hit")

    # ─── X + ARRIBA ──────────────────────────────────────────
    def _up(self):
        o = self.owner
        if self.phase in (1, 2):
            if self.prop_used:
                return
            self.prop_used  = True
            self.prop_timer = self.PROP_FRAMES
            o.vy = -5.5
            o.on_ground = False
            # Los propulsores dañan a los que estan abajo al activarse
            hb = pygame.Rect(o.rect.x - 14, o.rect.bottom - 4, o.rect.w + 28, 70)
            for other in self.fighters:
                if other is o or not other.alive:
                    continue
                if hb.colliderect(other.rect):
                    d = 1 if other.rect.centerx >= o.rect.centerx else -1
                    other.receive_hit(o.atk_power * 0.8, d, attacker=o, launch=0.7)
                    AUDIO_MGR.play("hit")
            self.add_fx(o.rect.centerx, o.rect.bottom, 40, C_ORANGE, 14, "flash")
        else:
            self.arm_state = "up"
            self.arm_timer = 20
            self.arm_total = 160
            o.vy = -13
            o.on_ground = False

    def _update_prop(self):
        o = self.owner
        self.prop_timer -= 1
        o.vy = -5.5

    def _update_arm(self):
        o = self.owner
        self.arm_total -= 1
        if self.arm_state == "up":
            self.arm_timer -= 1
            o.vy = -13
            o.vx = o.facing * 2
            if self.arm_timer <= 0:
                self.arm_state = "dive"
            return
        # Cae en diagonal con el brazo corrupto
        o.vx = o.facing * 8
        o.vy = max(o.vy, 17)
        if o.on_ground or self.arm_total <= 0:
            self.arm_state = None
            o.vx = 0
            # Terremoto fuerte: daña a todos, pero a Gamer le cuesta MUCHO
            self.quake(o.atk_power * 1.8, launch=1.2, self_damage=22)
            AUDIO_MGR.play("explosion")

    # ─── PROYECTILES / TRAMPA ────────────────────────────────
    def _nearest_enemy(self, x, y):
        o = self.owner
        best, best_d = None, 1e9
        for e in self.fighters:
            if e is o or not e.alive:
                continue
            d = math.hypot(e.rect.centerx - x, e.rect.centery - y)
            if d < best_d:
                best, best_d = e, d
        return best

    def _explode_missile(self, m):
        o = self.owner
        self.aoe(m["x"], m["y"], 75, o.atk_power * 1.1, launch=1.0)
        self.add_fx(m["x"], m["y"], 85, C_ORANGE, 20, "flash")
        self.add_fx(m["x"], m["y"], 110, C_YELLOW, 24)
        AUDIO_MGR.play("explosion")
        # La explosion cerca de Gamer le da un pequeño boost de salto
        if math.hypot(o.rect.centerx - m["x"], o.rect.centery - m["y"]) <= 110:
            o.vy = -12
            o.on_ground = False

    def _update_missiles(self):
        o = self.owner
        for m in self.missiles[:]:
            m["life"] -= 1
            if m["kind"] == "down":
                m["vy"] = min(m["vy"] + 0.6, 16)
            else:
                target = self._nearest_enemy(m["x"], m["y"])
                if target:
                    dx = target.rect.centerx - m["x"]
                    dy = target.rect.centery - m["y"]
                    dist = math.hypot(dx, dy) or 1.0
                    m["vx"] += (dx / dist * 6.5 - m["vx"]) * 0.12
                    m["vy"] += (dy / dist * 6.5 - m["vy"]) * 0.12
            m["x"] += m["vx"]
            m["y"] += m["vy"]
            m["rect"].center = (int(m["x"]), int(m["y"]))

            done = False
            if m["kind"] == "down":
                hit_plat = any(m["rect"].colliderect(p) for p in self.platforms)
                hit_foe  = any(e is not o and e.alive and m["rect"].colliderect(e.rect)
                               for e in self.fighters)
                if hit_plat or hit_foe:
                    self._explode_missile(m)
                    done = True
            else:
                for e in self.fighters:
                    if e is not o and e.alive and m["rect"].colliderect(e.rect):
                        d = 1 if m["vx"] >= 0 else -1
                        e.receive_hit(o.atk_power * 0.55, d, attacker=o, launch=0.6)
                        self.add_fx(m["x"], m["y"], 36, C_ORANGE, 14, "flash")
                        AUDIO_MGR.play("hit")
                        done = True
                        break
            if (done or m["life"] <= 0 or m["x"] < -250 or m["x"] > WIN_W + 250
                    or m["y"] > WIN_H + 250 or m["y"] < -400):
                self.missiles.remove(m)

    def _update_trap(self):
        t = self.trap
        if not t or t["landed"]:
            return
        t["vy"] += 0.6
        ny = t["y"] + t["vy"]
        for p in self.platforms:
            if p.left - 6 <= t["x"] <= p.right + 6 and t["y"] <= p.top <= ny:
                t["y"] = float(p.top)
                t["vy"] = 0.0
                t["landed"] = True
                return
        t["y"] = ny
        if t["y"] > WIN_H + 80:
            self.trap = None

    # ─── UPDATE / DRAW ───────────────────────────────────────
    def update(self, fighters, platforms, keys_held, special_pressed, special_released):
        o = self.owner
        self.fighters, self.platforms = fighters, platforms
        if self.phase_cd > 0:
            self.phase_cd -= 1
        if self.missile_cd > 0:
            self.missile_cd -= 1
        if self.grounded() and self.prop_timer == 0:
            self.prop_used = False

        if special_pressed:
            self.activate(keys_held)
        if special_released:
            self.deactivate_special()

        if self.charging:
            self._update_charge()
        if self.dash_timer > 0:
            self._update_dash()
        if self.diag:
            self._update_diag()
        if self.slam:
            self._update_slam()
        if self.prop_timer > 0:
            self._update_prop()
        if self.arm_state:
            self._update_arm()
        self._update_missiles()
        self._update_trap()
        self._update_fx()

    def draw(self, surface):
        o   = self.owner
        col = self.PHASE_COLORS[self.phase]

        # Aura de la fase actual + etiqueta
        pygame.draw.rect(surface, col, o.rect.inflate(6, 6), 1, border_radius=6)
        if self.phase == 3:
            for _ in range(2):          # efecto glitch
                gx = o.rect.x + random.randint(-4, o.rect.w)
                gy = o.rect.y + random.randint(0, o.rect.h)
                pygame.draw.rect(surface, random.choice([(255, 0, 200), (0, 255, 200), (255, 255, 255)]),
                                 (gx, gy, random.randint(6, 18), 2))
        lbl = get_font("consolas", 9, True).render(self.PHASE_NAMES[self.phase], True, col)
        surface.blit(lbl, (o.rect.x, o.rect.bottom + 11))

        # JARONA: barra de carga
        if self.charging:
            pct = min(self.charge / 120.0, 1.0)
            pygame.draw.rect(surface, (50, 50, 50), (o.rect.x, o.rect.top - 8, o.rect.w, 5), border_radius=2)
            pygame.draw.rect(surface, C_RED if pct >= 1 else C_YELLOW,
                             (o.rect.x, o.rect.top - 8, int(o.rect.w * pct), 5), border_radius=2)
            pygame.draw.rect(surface, C_CYAN, o.rect.inflate(10, 10), 2, border_radius=8)
        # JARONA: estela del dash
        if self.dash_timer > 0:
            for i in range(1, 5):
                x = o.rect.x - o.facing * i * 14
                s = pygame.Surface((o.rect.w, o.rect.h), pygame.SRCALPHA)
                s.fill((0, 200, 255, 90 - i * 18))
                surface.blit(s, (x, o.rect.y))

        # Carga diagonal / golpe al suelo
        if self.diag:
            pygame.draw.line(surface, C_CYAN, (o.rect.centerx - self.diag_dir * 22, o.rect.top - 14),
                             (o.rect.centerx, o.rect.centery), 3)
        if self.slam:
            pygame.draw.rect(surface, C_ORANGE, (o.rect.x + 6, o.rect.bottom, o.rect.w - 12, 8), border_radius=3)

        # Propulsores
        if self.prop_timer > 0:
            for dx in (o.rect.x + 10, o.rect.right - 10):
                pts = [(dx - 5, o.rect.bottom), (dx + 5, o.rect.bottom),
                       (dx, o.rect.bottom + random.randint(12, 26))]
                pygame.draw.polygon(surface, random.choice([C_ORANGE, C_YELLOW, C_FIRE]), pts)

        # Brazo corrupto
        if self.arm_state:
            ax = o.rect.right if o.facing == 1 else o.rect.left - 18
            pygame.draw.rect(surface, (255, 0, 200), (ax, o.rect.top + 6, 18, 28), border_radius=4)
            pygame.draw.rect(surface, (0, 255, 200), (ax + random.randint(0, 6), o.rect.top + 12, 8, 4))

        # Misiles
        for m in self.missiles:
            r = m["rect"]
            pygame.draw.rect(surface, C_RED if m["kind"] == "down" else C_CYAN, r, border_radius=3)
            pygame.draw.circle(surface, random.choice([C_ORANGE, C_YELLOW]),
                               (int(m["x"] - m["vx"] * 1.5), int(m["y"] - m["vy"] * 1.5)), 4)

        # Trampa glitch
        if self.trap:
            tx, ty = int(self.trap["x"]), int(self.trap["y"])
            for _ in range(5):
                gx = tx + random.randint(-14, 8)
                gy = ty - random.randint(2, 14)
                pygame.draw.rect(surface, random.choice([(255, 0, 200), (0, 255, 200), (255, 255, 255)]),
                                 (gx, gy, random.randint(4, 12), random.randint(2, 5)))
            pygame.draw.rect(surface, (255, 0, 200), (tx - 14, ty - 3, 28, 3))

        self._draw_fx(surface)


# ═══════════════════════ FIGHTER ═══════════════════════

class Fighter:
    def __init__(self, path, x, y, sprite, color, character="kirby", is_player=False,
                 file_size=None, display_name=None):
        self.path       = path
        self.name       = display_name or os.path.basename(path)
        self.short      = self.name[:14] + ("…" if len(self.name)>14 else "")
        self.sprite     = sprite
        self.color      = color
        self.character  = character
        self.is_player  = is_player

        self.rect       = pygame.Rect(x, y, SPRITE_SIZE, SPRITE_SIZE)
        self.vx         = 0.0
        self.vy         = 0.0
        self.on_ground  = False
        self.damage     = 0
        self.alive      = True

        self.attack_cd  = 0
        self.atk_active = False
        self.atk_timer  = 0
        self.knockback_timer = 0
        self.facing     = 1
        self.jump_count = 0

        # Saltos segun personaje
        self.MAX_JUMPS  = 7 if character == "kirby" else 2

        # Stats segun el PESO del archivo (ver file_profile)
        if file_size is None:
            file_size = os.path.getsize(path)
        prof = file_profile(file_size)
        self.file_size  = int(file_size)
        self.size_t     = prof["t"]
        self.weight     = prof["weight"]
        self.speed_mod  = prof["speed"]
        self.atk_power  = (16 + random.uniform(0, 4)) * prof["dmg"]
        self.atk_rate   = prof["atk"]          # velocidad de ataque (cooldown = base / atk_rate)

        # Sistema de personaje
        self.kirby = KirbyAbilities(self) if character == "kirby" else None
        self.kris  = KrisAbilities(self)  if character == "kris" else None
        self.gamer = GamerAbilities(self) if character == "gamer64" else None
        self.special = self.kirby or self.kris or self.gamer

        # IA
        self.ai_target  = None
        self.ai_timer   = 0
        self.ai_jump_cd = 0
        self.ai_special_cd = 0

        # Teclas previas (para detectar press/release de X)
        self._prev_special = False

        # Estados nuevos (Kris / Gamer64)
        self.paralyzed    = 0          # frames de paralisis restantes (Soul de Kris)
        self.paralyzed_by = None
        self.jump_buffer  = 0
        self.combo_step   = 0
        self.combo_timer  = 0
        self.atk_step     = 1
        self.atk_hit_ids  = set()
        self.ai_release   = 0
        self.attack_range = 85 if character == "kris" else ATTACK_RANGE
        self.single_hit   = character in ("kris", "gamer64")   # 1 golpe por ataque
        self.remote       = False      # multijugador: jugador remoto (lo controla otro)
        self.captured     = None       # None | 'held' (dentro de Kirby) | 'star' (escupido como estrella)
        self.captor       = None
        self.star_t       = 0
        self.star_dir     = 1
        self.star_power   = 0.0

    # ── FISICA ──────────────────────────────────────────────
    def apply_gravity(self):
        if self.is_rock():
            return   # gravedad manejada por roca
        if self.special and self.special.skip_gravity():
            return   # Gamer: JARONA / propulsion
        if not self.on_ground:
            self.vy += GRAVITY
        self.vy = min(self.vy, 22)

    def is_rock(self):
        return self.kirby and self.kirby.is_rock

    def move(self, platforms):
        self.on_ground = False
        self.rect.x   += int(self.vx)
        self._collide_x(platforms)
        self.rect.y   += int(self.vy)
        self._collide_y(platforms)
        if self.on_ground:
            self.vx *= 0.72
        else:
            self.vx *= 0.90

    def _collide_x(self, platforms):
        for p in platforms:
            if self.rect.colliderect(p):
                if self.vx > 0: self.rect.right = p.left
                elif self.vx < 0: self.rect.left = p.right
                self.vx = 0

    def _collide_y(self, platforms):
        for p in platforms:
            if self.rect.colliderect(p):
                if self.vy > 0:
                    self.rect.bottom = p.top
                    self.vy = 0
                    self.on_ground  = True
                    self.jump_count = 0
                elif self.vy < 0:
                    self.rect.top  = p.bottom
                    self.vy = 0

    def jump(self):
        if self.paralyzed > 0:
            return
        # Espada de Kirby bloquea saltar
        if self.kirby and self.kirby.sword_active:
            return
        if self.special and self.special.blocks_jump():
            return
        if self.jump_count < self.MAX_JUMPS:
            force = JUMP_FORCE * (0.75 if self.jump_count > 0 else 1.0)
            self.vy = force
            self.jump_count += 1
            self.on_ground  = False
            AUDIO_MGR.play("kirby_jump", volume=0.5)

    def request_jump(self):
        """Salto pedido por el jugador (Kris lo retrasa unos frames para poder hacer ACT en el suelo)."""
        delay = self.special.jump_delay if self.special else 0
        if delay > 0:
            self.jump_buffer = delay
        else:
            self.jump()

    def receive_hit(self, power, direction, attacker=None, launch=1.0):
        if self.captured:
            return                      # absorbido o volando como estrella: no recibe golpes
        # Roca bloquea el daño y acumula para romperla
        if self.kirby and self.kirby.rock_absorb_damage(power):
            return
        self.damage = min(self.damage + int(power), MAX_DAMAGE)
        kb = (KNOCKBACK_BASE + self.damage*DAMAGE_SCALE) * (power/12) / self.weight * launch
        self.vx = direction * kb * random.uniform(0.85, 1.15)
        self.vy = -kb * 0.55
        self.knockback_timer = 12
        # Si Kris lo golpea, se libera de la paralisis del Soul
        if self.paralyzed > 0 and attacker is not None and attacker is self.paralyzed_by:
            self.paralyzed = 0
            self.paralyzed_by = None

    def resolve_normal_attack(self, fighters):
        """Aplica el golpe Z de este luchador a los enemigos dentro de su hitbox."""
        hb = self.get_hitbox()
        if not hb:
            return
        for other in fighters:
            if other is self or not other.alive:
                continue
            if self.single_hit and id(other) in self.atk_hit_ids:
                continue
            if not hb.colliderect(other.rect):
                continue
            d = 1 if other.rect.centerx > self.rect.centerx else -1
            power, launch = self.atk_power, 1.0
            if self.character == "kris":
                if self.atk_step == 1:
                    power, launch = power * 0.7, 0.55     # golpes 1 y 2: se quedan cerca para el combo
                elif self.atk_step == 2:
                    power, launch = power * 0.85, 0.55
                else:
                    # 3er golpe: mas daño acumulado en el enemigo = sale volando mas lejos
                    power  *= 1.1
                    launch  = 1.0 + min(other.damage, 300) / 200.0
            elif self.character == "gamer64":
                power *= 0.9
            other.receive_hit(power, d, attacker=self, launch=launch)
            self.atk_hit_ids.add(id(other))
            AUDIO_MGR.play("hit")

    def release_captured(self, stun=14):
        """Deja de estar absorbido / de ser estrella y vuelve a ser un luchador normal."""
        self.captured = None
        self.captor = None
        self.vx, self.vy = 0.0, -4.0
        self.knockback_timer = max(self.knockback_timer, stun)

    def _update_captured(self, fighters):
        c = self.captor
        if self.captured == "held":                       # dentro de Kirby: sigue su posicion
            if c is None or not c.alive:
                self.release_captured()
                return
            self.rect.center = c.rect.center
            self.vx = self.vy = 0
            return
        # estrella: sale disparado hacia donde miraba Kirby
        self.star_t -= 1
        self.rect.x += int(self.star_dir * STAR_SPEED)
        hit = None
        for other in fighters:
            if other is self or other is c or not other.alive or other.captured:
                continue
            if self.rect.colliderect(other.rect):
                hit = other
                break
        if hit is not None:                               # los dos reciben daño
            hit.receive_hit(self.star_power, self.star_dir, attacker=c)
            self.damage = min(self.damage + int(self.star_power * 0.4), MAX_DAMAGE)
            AUDIO_MGR.play("hit")
            self.release_captured()
        elif self.star_t <= 0 or self.rect.left <= 8 or self.rect.right >= WIN_W - 8:
            self.release_captured()

    def is_out_of_bounds(self):
        if self.captured:
            return False
        return (self.rect.top > WIN_H+100 or self.rect.bottom < -400 or
                self.rect.right < -300    or self.rect.left > WIN_W+300)

    # ── ATAQUE NORMAL (Z) ────────────────────────────────────
    def try_attack(self):
        if self.attack_cd > 0:
            return
        self.atk_active  = True
        self.atk_timer   = 6
        self.atk_hit_ids = set()
        if self.character == "kris":
            # Combo de espada: maximo 3 golpes seguidos, el 3ro lanza al enemigo
            if self.combo_timer > 0 and self.combo_step < 3:
                self.combo_step += 1
            else:
                self.combo_step = 1
            self.atk_step    = self.combo_step
            self.combo_timer = int(42 / self.atk_rate)
            self.attack_cd   = int((50 if self.combo_step == 3 else 16) / self.atk_rate)
            AUDIO_MGR.play("kris_slash")
        elif self.character == "gamer64":
            self.attack_cd = int(24 / self.atk_rate)
        else:
            self.attack_cd = int(ATTACK_CD / self.atk_rate)

    def get_hitbox(self):
        if not self.atk_active:
            return None
        hb = self.rect.inflate(self.attack_range, 10)
        if self.facing == 1: hb.left  = self.rect.centerx
        else:                hb.right = self.rect.centerx
        return hb

    # ── UPDATE ───────────────────────────────────────────────
    def update(self, fighters, platforms, keys=None, special_pressed=False, special_released=False):
        if not self.alive:
            return
        if self.captured:
            self._update_captured(fighters)
            return

        if self.knockback_timer > 0:
            self.knockback_timer -= 1
        if self.attack_cd > 0:
            self.attack_cd -= 1
        if self.combo_timer > 0:
            self.combo_timer -= 1
        if self.atk_timer > 0:
            self.atk_timer -= 1
        else:
            self.atk_active = False
        if self.jump_buffer > 0:
            self.jump_buffer -= 1
            if self.jump_buffer == 0:
                self.jump()

        if self.special:
            if keys:
                keys_held = keys
            elif self.is_player or self.remote:
                keys_held = pygame.key.get_pressed()
            else:
                keys_held = FakeKeys()                  # la IA no lee el teclado real
            sp = special_pressed and self.paralyzed <= 0
            self.special.update(fighters, platforms,
                                keys_held, sp, special_released)

        if self.paralyzed > 0:
            # Paralizado (Soul de Kris): no puede moverse ni atacar
            self.paralyzed -= 1
            if self.paralyzed == 0:
                self.paralyzed_by = None
            if self.knockback_timer <= 0:
                self.vx = 0
        elif (self.is_player or self.remote) and keys:
            self._player_input(keys, special_pressed)
        else:
            self._ai_update(fighters, platforms)

        self.apply_gravity()
        self.move(platforms)

    def _player_input(self, keys, special_pressed):
        if self.knockback_timer > 4:
            return
        if self.is_rock():
            return  # inmovilizado en roca
        if self.kirby and self.kirby.sword_active:
            return  # inmovilizado en espada
        if self.special and self.special.input_locked():
            return  # inmovilizado por su habilidad
        if keys[K_LEFT]:
            self.vx = -MOVE_SPEED * self.speed_mod
            self.facing = -1
        if keys[K_RIGHT]:
            self.vx =  MOVE_SPEED * self.speed_mod
            self.facing = 1
        if keys[K_ATTACK]:
            self.try_attack()

    def _ai_update(self, fighters, platforms):
        # La IA suelta X despues de un rato (martillo de Kirby, JARONA de Gamer...)
        if self.ai_release > 0:
            self.ai_release -= 1
            if self.ai_release == 0 and self.special:
                self.special.deactivate_special()

        if (self.knockback_timer > 0 or self.is_rock()
                or (self.special and self.special.input_locked())):
            return

        # Target: el mas cercano
        self.ai_timer -= 1
        if self.ai_timer <= 0 or not self.ai_target or not self.ai_target.alive:
            enemies = [f for f in fighters if f is not self and f.alive]
            if not enemies:
                return
            self.ai_target = min(enemies,
                key=lambda f: abs(f.rect.centerx - self.rect.centerx))
            self.ai_timer = random.randint(30, 80)

        t  = self.ai_target
        dx = t.rect.centerx - self.rect.centerx
        dist = abs(dx)

        if dist > ATTACK_RANGE * 0.7:
            d = 1 if dx > 0 else -1
            self.vx += d * AI_SPEED * self.speed_mod * 0.4
            self.vx  = max(-AI_SPEED*self.speed_mod, min(self.vx, AI_SPEED*self.speed_mod))
            self.facing = d
        else:
            self.try_attack()
            self.facing = 1 if dx > 0 else -1

            # IA usa especial ocasionalmente
            self.ai_special_cd -= 1
            if self.ai_special_cd <= 0 and self.special and random.random() < 0.02:
                self.special.activate(FakeKeys(*random.choice(AI_INTENTS)))
                self.ai_release    = random.randint(15, 70)
                self.ai_special_cd = random.randint(120, 300)

        self.ai_jump_cd -= 1
        near_edge    = self.rect.left < 80 or self.rect.right > WIN_W - 80
        target_above = t.rect.centery < self.rect.centery - 60
        if self.ai_jump_cd <= 0 and (target_above or near_edge) and self.on_ground:
            self.jump()
            self.ai_jump_cd = random.randint(40, 90)

        if near_edge and self.on_ground:
            self.vx += (-1 if self.rect.centerx > WIN_W//2 else 1) * 1.2

    # ── DRAW ─────────────────────────────────────────────────
    def draw(self, surface):
        if not self.alive:
            return
        if self.captured == "held":                     # esta dentro de Kirby
            return
        if self.captured == "star":                     # volando como estrella
            cx, cy = self.rect.center
            for i in range(1, 4):
                pygame.draw.circle(surface, (255, 220, 60), (cx - self.star_dir * i * 14, cy), max(2, 8 - i * 2))
            draw_star(surface, cx, cy, 26, (255, 235, 60))
            draw_star(surface, cx, cy, 12, (255, 255, 255))
            return

        spr = self.sprite
        if self.facing == -1:
            spr = pygame.transform.flip(spr, True, False)
        surface.blit(spr, self.rect.topleft)

        # Indicador de personaje (etiqueta pequeña, solo si no es none)
        char_font = get_font("consolas", 9, True)
        if self.character == "none":
            char_lbl = char_font.render("—", True, C_GRAY)
        else:
            char_lbl = char_font.render(self.character.upper(), True, C_PINK)
        surface.blit(char_lbl, (self.rect.x, self.rect.bottom + 1))

        if self.is_player:
            pygame.draw.rect(surface, C_YELLOW, self.rect.inflate(4,4), 2, border_radius=4)

        # Hitbox normal
        hb = self.get_hitbox()
        if hb:
            s = pygame.Surface((hb.w, hb.h), pygame.SRCALPHA)
            s.fill((255,255,100,55))
            surface.blit(s, hb.topleft)

        # Efectos del personaje
        if self.special:
            self.special.draw(surface)

        # Paralizado por el Soul de Kris
        if self.paralyzed > 0:
            ov = pygame.Surface((self.rect.w, self.rect.h), pygame.SRCALPHA)
            ov.fill((255, 60, 90, 90))
            surface.blit(ov, self.rect.topleft)
            pygame.draw.rect(surface, (255, 60, 90), self.rect.inflate(4, 4), 2, border_radius=4)
            bar = int(self.rect.w * self.paralyzed / (10 * FPS))
            pygame.draw.rect(surface, (255, 60, 90), (self.rect.x, self.rect.top - 4, bar, 3))

        # % de daño
        dmg_font = get_font("consolas", 13, True)
        col = C_GREEN if self.damage < 50 else (C_YELLOW if self.damage < 120 else C_RED)
        lbl = dmg_font.render(f"{self.damage}%", True, col)
        surface.blit(lbl, (self.rect.centerx - lbl.get_width()//2, self.rect.top - 18))


# ═══════════════════════ HUD ═══════════════════════

def draw_hud(surface, fighters, round_num, total_rounds, title=None):
    font_s = get_font("segoeui", 11)
    font_b = get_font("segoeui", 13, True)
    font_t = get_font("segoeui", 15, True)

    hdr = font_t.render(title or f"FILE SMASH  —  Ronda {round_num}/{total_rounds}", True, C_YELLOW)
    surface.blit(hdr, (WIN_W//2 - hdr.get_width()//2, 8))

    cols    = min(len(fighters), 6)
    box_w, box_h, gap = 155, 36, 6
    start_x = (WIN_W - (cols*(box_w+gap))) // 2
    start_y = WIN_H - (math.ceil(len(fighters)/6)) * (box_h+gap) - 8

    for i, f in enumerate(fighters):
        col = i % 6
        row = i // 6
        x   = start_x + col*(box_w+gap)
        y   = start_y + row*(box_h+gap)

        bg  = (15,15,25) if f.alive else (40,15,15)
        s   = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        s.fill((*bg, 200))
        surface.blit(s, (x,y))

        mini = pygame.transform.scale(f.sprite, (28,28))
        surface.blit(mini, (x+3, y+4))

        nlbl = font_s.render(f.short, True, C_GRAY if not f.alive else C_WHITE)
        surface.blit(nlbl, (x+34, y+3))

        # Etiqueta de personaje en HUD
        if f.character == "none":
            clbl = font_s.render("—", True, C_GRAY)
        else:
            clbl = font_s.render(f.character.upper(), True, C_PINK)
        surface.blit(clbl, (x+34+nlbl.get_width()+4, y+3))

        if f.alive:
            pct_capped = min(f.damage, 200)
            bar_w  = int((box_w-36) * pct_capped/200)
            bar_col= C_GREEN if f.damage < 50 else (C_YELLOW if f.damage < 120 else C_RED)
            pygame.draw.rect(surface, (50,50,50), (x+34, y+20, box_w-36, 10), border_radius=3)
            if bar_w > 0:
                pygame.draw.rect(surface, bar_col, (x+34, y+20, bar_w, 10), border_radius=3)
            dlbl = font_b.render(f"{f.damage}%", True, bar_col)
            surface.blit(dlbl, (x+box_w-dlbl.get_width()-3, y+18))
        else:
            elim = font_s.render("ELIMINADO", True, C_RED)
            surface.blit(elim, (x+34, y+18))

        if f.is_player:
            pygame.draw.rect(surface, C_YELLOW, (x,y,box_w,box_h), 2, border_radius=2)

    return start_y


# ═══════════════════════ ESCENARIO ═══════════════════════

def draw_stage(surface, platforms):
    for y in range(WIN_H):
        t = y/WIN_H
        pygame.draw.line(surface, (int(10+20*t), int(10+15*t), int(20+35*t)),
                         (0,y), (WIN_W,y))
    for p in platforms:
        pygame.draw.rect(surface, C_PLATFORM,   p, border_radius=4)
        pygame.draw.rect(surface, C_PLATFORM_T,
                         pygame.Rect(p.x, p.y, p.w, 5), border_radius=4)
        pygame.draw.rect(surface, (50,35,20),   p, 2, border_radius=4)


def make_platforms(n):
    main   = pygame.Rect(150, 430, 700, 22)
    left   = pygame.Rect(60,  330, 180, 16)
    right  = pygame.Rect(760, 330, 180, 16)
    center = pygame.Rect(385, 300, 230, 16)
    plats  = [main, left, right]
    if n <= 6:
        plats.append(center)
    return plats


# ═══════════════════════ MULTIJUGADOR: RED ═══════════════════════
# Como funciona (resumen):
#   - Un servidor "relay" (RELAYSERV.py) une al HOST con los demas jugadores.
#   - El HOST es el unico que simula la pelea. Cada jugador le manda sus teclas
#     y el host le devuelve el estado de todos (30 veces por segundo, comprimido).
#   - Cada jugador solo manda LAS TECLAS y una imagen pequeña de su archivo:
#     el archivo en si nunca sale de tu PC, y en multijugador NO se borra nada.

KEYBIT = {K_LEFT: 1, K_RIGHT: 2, K_UP: 4, K_DOWN: 8, K_ATTACK: 16, K_SPECIAL: 32, K_COMMA: 64}
EDGE_JUMP, EDGE_X_DOWN, EDGE_X_UP = 1, 2, 4


class MaskKeys:
    """Teclas guardadas como un numero (bits). Se usa igual que pygame.key.get_pressed()."""
    def __init__(self, mask=0):
        self.mask = mask

    def __getitem__(self, key):
        return bool(self.mask & KEYBIT.get(key, 0))


class RemoteInput:
    """Ultimas teclas recibidas de un jugador remoto."""
    def __init__(self):
        self.mask  = 0
        self.edges = []

    def feed(self, d):
        try:
            self.mask = int(d.get("k", 0)) & 127
            for e in list(d.get("e", []))[:8]:
                if e in (EDGE_JUMP, EDGE_X_DOWN, EDGE_X_UP):
                    self.edges.append(e)
        except Exception:
            pass

    def take_edges(self):
        e, self.edges = self.edges, []
        return e


class LocalInput:
    """Lee tu teclado y lo convierte en (mascara de teclas, eventos de un solo frame)."""
    def __init__(self):
        self.prev_x = False
        self.jump_pending = False

    def on_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == K_JUMP:
            self.jump_pending = True

    def read(self):
        keys = pygame.key.get_pressed()
        mask = 0
        for k, bit in KEYBIT.items():
            if keys[k]:
                mask |= bit
        cur_x = bool(keys[K_SPECIAL])
        edges = []
        if self.jump_pending:
            edges.append(EDGE_JUMP)
            self.jump_pending = False
        if cur_x and not self.prev_x:
            edges.append(EDGE_X_DOWN)
        if self.prev_x and not cur_x:
            edges.append(EDGE_X_UP)
        self.prev_x = cur_x
        return mask, edges


# ── Serializacion del estado de los luchadores ───────────────
_SKIP_F  = {"sprite", "special", "kirby", "kris", "gamer", "ai_target", "paralyzed_by",
            "is_player", "remote", "atk_hit_ids", "captor"}
_SKIP_S  = {"owner", "fighters", "platforms"}
_NOPE    = object()


def _enc(v):
    if v is None or isinstance(v, (bool, str, int)):
        return v
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, pygame.Rect):
        return {"__r": [v.x, v.y, v.w, v.h]}
    if isinstance(v, (list, tuple)):
        out = []
        for x in v:
            e = _enc(x)
            if e is _NOPE:
                return _NOPE
            out.append(e)
        return out
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            e = _enc(x)
            if e is _NOPE:
                return _NOPE
            out[str(k)] = e
        return out
    return _NOPE


def _dec(v):
    if isinstance(v, dict):
        if len(v) == 1 and "__r" in v:
            return pygame.Rect(*v["__r"])
        return {k: _dec(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_dec(x) for x in v]
    return v


def ser_fighter(f):
    """Estado completo (plano) de un luchador y de su habilidad, listo para JSON."""
    d = {}
    for k, v in f.__dict__.items():
        if k in _SKIP_F:
            continue
        e = _enc(v)
        if e is not _NOPE:
            d[k] = e
    sp = f.special
    if sp:
        for k, v in sp.__dict__.items():
            if k in _SKIP_S:
                continue
            e = _enc(v)
            if e is not _NOPE:
                d["sp." + k] = e
        if isinstance(sp, KrisAbilities):
            d["sp._net_heals"] = sp.heals_left
        if isinstance(sp, KirbyAbilities) and sp.copy is not None:       # habilidad copiada
            for k, v in sp.copy.__dict__.items():
                if k in _SKIP_S:
                    continue
                e = _enc(v)
                if e is not _NOPE:
                    d["spc." + k] = e
            if isinstance(sp.copy, KrisAbilities):
                d["spc._net_heals"] = sp.copy.heals_left
    return d


def apply_fighter(f, d):
    copy_items = []
    for k, v in d.items():
        if k.startswith("spc."):
            copy_items.append((k[4:], v))
        elif k.startswith("sp."):
            if f.special:
                setattr(f.special, k[3:], _dec(v))
        elif k not in _SKIP_F:
            setattr(f, k, _dec(v))
    sp = f.special
    if isinstance(sp, KirbyAbilities):               # Kirby con una habilidad copiada
        want = {"kris": KrisAbilities, "gamer64": GamerAbilities}.get(sp.copy_kind)
        if want is None:
            sp.copy = None
        elif not isinstance(sp.copy, want):
            sp.copy = want(f)
        if sp.copy is not None:
            for k, v in copy_items:
                setattr(sp.copy, k, _dec(v))


def _safe_decompress(data, limit=4 * 1024 * 1024):
    dec = zlib.decompressobj()
    out = dec.decompress(data, limit)
    if dec.unconsumed_tail:
        raise ValueError("paquete demasiado grande")
    return out


def encode_sprite(surf):
    tb = getattr(pygame.image, "tobytes", None) or pygame.image.tostring
    return base64.b64encode(zlib.compress(tb(surf, "RGBA"), 6)).decode("ascii")


def decode_sprite(s, name="?"):
    try:
        raw = _safe_decompress(base64.b64decode(s), SPRITE_SIZE * SPRITE_SIZE * 4 + 1)
        if len(raw) != SPRITE_SIZE * SPRITE_SIZE * 4:
            raise ValueError("tamaño de sprite invalido")
        return pygame.image.frombuffer(raw, (SPRITE_SIZE, SPRITE_SIZE), "RGBA").copy()
    except Exception:
        return _placeholder(name, SPRITE_SIZE)


# ── Codigos de sala LAN ──────────────────────────────────────
def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def lan_encode(ip):
    try:
        a, b, c, d = [int(x) for x in ip.split(".")]
        return "%02X%02X%02X%02X" % (a, b, c, d)
    except Exception:
        return "7F000001"


def lan_decode(code):
    c = code.replace("-", "").strip()
    if len(c) == 8 and all(ch in "0123456789abcdefABCDEF" for ch in c):
        return ".".join(str(int(c[i:i + 2], 16)) for i in (0, 2, 4, 6))
    return None


def pretty_code(c):
    return c[:4] + "-" + c[4:] if len(c) == 8 else c


# ── Conexion ─────────────────────────────────────────────────
def _ws_open(url):
    """Abre el WebSocket (compatible con varias versiones de la libreria websockets)."""
    try:
        return ws_connect(url, open_timeout=60, max_size=2 ** 22, legacy=True)
    except TypeError:
        return ws_connect(url, open_timeout=60, max_size=2 ** 22)


class NetClient:
    """Conexion WebSocket en segundo plano (no congela la ventana)."""
    def __init__(self):
        self.ws        = None
        self.inbox     = queue.Queue()
        self.state     = "idle"          # idle | connecting | open | closed | error
        self.error     = ""
        self.last_send = time.time()
        self._lock     = threading.Lock()

    def start(self, url, first_msg):
        self.state = "connecting"

        def run():
            try:
                self.ws = _ws_open(url)
                self.ws.send(json.dumps(first_msg))
                self.state = "open"
            except Exception as e:
                self.error = f"No se pudo conectar a {url}: {e}"
                self.state = "error"
                self.inbox.put(None)
                return
            try:
                for msg in self.ws:
                    self.inbox.put(msg)
            except Exception as e:
                self.error = str(e)
            if self.state != "error":
                self.state = "closed"
            self.inbox.put(None)

        threading.Thread(target=run, daemon=True).start()

    def send(self, obj):
        if self.state != "open" or self.ws is None:
            return
        data = bytes(obj) if isinstance(obj, (bytes, bytearray)) else json.dumps(obj, separators=(",", ":"))
        with self._lock:
            try:
                self.ws.send(data)
                self.last_send = time.time()
            except Exception as e:
                self.error = str(e)
                self.state = "closed"

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        ws, self.ws = self.ws, None
        self.state = "closed"
        if ws is not None:
            threading.Thread(target=lambda: ws.close(), daemon=True).start()


def make_player_info(path, char):
    surf = load_sprite(path)
    return {"name": os.path.basename(path)[:40], "char": char, "path": path,
            "size": max(1, os.path.getsize(path)), "surf": surf, "spr": encode_sprite(surf)}


class MPSession:
    """Una sala: la crea el host o te unes con un codigo. Maneja la lista de jugadores."""
    def __init__(self, me):
        self.me           = me
        self.role         = None
        self.net          = None
        self.pid          = None
        self.code         = ""
        self.display_code = ""
        self.status       = "idle"       # idle | connecting | lobby | error | closed
        self.error        = ""
        self.players      = {}
        self._stop_local  = None
        self.stake_lost   = False        # True si en esta pelea perdiste (y se borro) tu archivo
        self.stakes       = MP_STAKES    # la sala juega con apuesta

    # ── conectar ────────────────────────────────────────────
    def host(self, lan=False):
        self.role, self.pid, self.status = "host", 0, "connecting"
        if lan:
            try:
                if BASE_DIR not in sys.path:
                    sys.path.insert(0, BASE_DIR)
                import RELAYSERV
            except Exception as e:
                return self._fail(f"Falta RELAYSERV.py junto al juego (o la libreria websockets): {e}")
            _th, stop, err = RELAYSERV.start_background(LAN_PORT)
            if err is not None:
                return self._fail(f"No se pudo abrir el puerto {LAN_PORT} (¿ya hay una sala abierta?): {err}")
            self._stop_local = stop
            self.display_code = lan_encode(get_lan_ip())
            url = f"ws://127.0.0.1:{LAN_PORT}"
        else:
            if not SERVER_URL:
                return self._fail("Falta configurar SERVER_URL al inicio de file_smash.py "
                                  "(ver RELAYSERV.py). Mientras tanto usa la sala LAN.")
            url = SERVER_URL
        self.net = NetClient()
        self.net.start(url, {"t": "host"})

    def join(self, code):
        self.role, self.status = "client", "connecting"
        c = code.strip().upper().replace("-", "")
        ip = lan_decode(c)
        if ip is not None:
            url, join_code = f"ws://{ip}:{LAN_PORT}", "*"
        else:
            if not SERVER_URL:
                return self._fail("Ese codigo es de una sala online, pero SERVER_URL no esta configurado.")
            url, join_code = SERVER_URL, c
        self.net = NetClient()
        self.net.start(url, {"t": "join", "code": join_code})

    def _fail(self, msg):
        self.status = "error"
        self.error  = msg
        self.close()

    def close(self):
        if self.net is not None:
            if self.net.state == "open" and self.role == "client":
                self.net.send({"t": "leave"})
            self.net.close()
        if self._stop_local:
            self._stop_local()
            self._stop_local = None

    # ── enviar ──────────────────────────────────────────────
    def send_all(self, d):
        if self.net:
            self.net.send({"to": "all", "d": d})

    def _roster_msg(self):
        return {"t": "roster", "stakes": MP_STAKES, "players": [
            {"pid": pid, "name": p["name"], "char": p["char"], "size": p["size"]}
            for pid, p in sorted(self.players.items())]}

    def _broadcast_roster(self):
        self.send_all(self._roster_msg())

    def host_start(self):
        """El host arma la partida y avisa a todos. Devuelve (jugadores, plataformas)."""
        plist = [{"pid": pid, "name": p["name"], "char": p["char"], "size": p["size"], "spr": p["spr"]}
                 for pid, p in sorted(self.players.items())]
        plats = make_platforms(len(plist))
        self.send_all({"t": "start", "players": plist, "stakes": MP_STAKES,
                       "plats": [[r.x, r.y, r.w, r.h] for r in plats]})
        return plist, plats

    def change_me(self, info):
        """Cambias de archivo (por ejemplo porque perdiste el anterior)."""
        self.me = info
        if self.role == "host":
            self.players[0] = dict(info)
            self._broadcast_roster()
        elif self.net is not None and self.net.state == "open":
            self.net.send(self._hello())

    def after_match(self):
        if self.role == "host" and self.status == "lobby":
            self._broadcast_roster()

    # ── recibir ─────────────────────────────────────────────
    def pump(self):
        """Procesa lo recibido. Devuelve eventos: ('roster',), ('input',pid,d), ('peer_leave',pid),
        ('start',msg), ('cd',msg), ('end',msg), ('snap',bytes), ('host_left',), ('closed',motivo)."""
        ev = []
        if self.net is None:
            return ev
        for raw in self.net.poll():
            if raw is None:
                if self.status in ("error", "closed"):
                    continue
                if self.status == "connecting" or self.net.state == "error":
                    self._fail(self.net.error or "No se pudo conectar")
                else:
                    self.status = "closed"
                    ev.append(("closed", self.net.error or "Se perdio la conexion"))
                continue
            if isinstance(raw, (bytes, bytearray)):
                ev.append(("snap", bytes(raw)))
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if isinstance(msg, dict):
                self._handle(msg, ev)
        if self.net.state == "open" and time.time() - self.net.last_send > 12:
            self.net.send({"to": "all", "d": {"t": "ping"}} if self.role == "host" else {"t": "ping"})
        return ev

    def _hello(self):
        return {"t": "hello", "name": self.me["name"], "char": self.me["char"],
                "size": self.me["size"], "spr": self.me["spr"]}

    def _on_hello(self, pid, d):
        if pid not in self.players and len(self.players) >= MAX_PLAYERS:
            return
        name = str(d.get("name", "?"))[:40]
        char = d.get("char")
        char = char if char in CHARACTERS else "none"
        try:
            size = max(1, min(int(d.get("size", 1)), 10 ** 13))
        except Exception:
            size = 1
        spr = str(d.get("spr", ""))
        self.players[pid] = {"name": name, "char": char, "size": size, "spr": spr,
                             "surf": decode_sprite(spr, name)}
        self._broadcast_roster()

    def _handle(self, msg, ev):
        t = msg.get("t")
        if t == "error":
            return self._fail(str(msg.get("msg", "error del servidor")))
        if self.role == "host":
            if t == "hosted":
                self.code = str(msg.get("code", ""))
                if not self.display_code:
                    self.display_code = self.code
                self.players[0] = dict(self.me)
                self.status = "lobby"
                ev.append(("roster",))
            elif t == "peer_leave":
                pid = msg.get("pid")
                self.players.pop(pid, None)
                self._broadcast_roster()
                ev.append(("peer_leave", pid))
                ev.append(("roster",))
            elif "from" in msg and isinstance(msg.get("d"), dict):
                pid, d = msg["from"], msg["d"]
                if d.get("t") == "hello":
                    self._on_hello(pid, d)
                    ev.append(("roster",))
                elif d.get("t") == "in":
                    ev.append(("input", pid, d))
        else:
            if t == "joined":
                self.pid = msg.get("pid")
                self.status = "lobby"
                self.net.send(self._hello())
            elif t == "roster":
                self.players = {p["pid"]: p for p in msg.get("players", [])}
                self.stakes = bool(msg.get("stakes", False))
                ev.append(("roster",))
            elif t == "start":
                ev.append(("start", msg))
            elif t == "cd":
                ev.append(("cd", msg))
            elif t == "end":
                ev.append(("end", msg))
            elif t == "host_left":
                self.status = "closed"
                ev.append(("host_left",))


# ═══════════════════════ MULTIJUGADOR: PELEA ═══════════════════════

def _build_fighters(plist, plats, sprites, my_pid, host_mode):
    fighters = []
    main_plat = plats[0]
    spacing = main_plat.w // (len(plist) + 1)
    for i, p in enumerate(plist):
        x = main_plat.x + spacing * (i + 1) - SPRITE_SIZE // 2
        y = main_plat.top - SPRITE_SIZE - 2
        f = Fighter(f"net:{p['pid']}:{p['name']}", x, y, sprites[p["pid"]],
                    make_color_for(p["name"]), character=p["char"],
                    is_player=(p["pid"] == my_pid), file_size=p["size"],
                    display_name=p["name"])
        f.remote = bool(host_mode and p["pid"] != my_pid)    # el host simula a todos
        f.pid = p["pid"]
        fighters.append(f)
    return fighters


def _draw_banner(screen, text, color=C_YELLOW, y=WIN_H // 2):
    lbl = get_font("segoeui", 22, True).render(text, True, color)
    r = lbl.get_rect(center=(WIN_W // 2, y))
    pygame.draw.rect(screen, C_DARK, r.inflate(24, 16), border_radius=6)
    screen.blit(lbl, r)


def run_mp_host_match(screen, clock, sess, plist, plats, input_fn=None, max_frames=None):
    """Pelea multijugador vista desde el HOST (es quien simula). Devuelve el pid ganador o None."""
    MATCH_STATE.clear()
    sess.stake_lost = False
    AUDIO_MGR.play_music("music_battle")
    sprites  = {p["pid"]: sess.players[p["pid"]]["surf"] for p in plist}
    fighters = _build_fighters(plist, plats, sprites, 0, True)
    by_pid   = {f.pid: f for f in fighters}
    sess.last_fighters = fighters      # (para pruebas / depuracion)
    inputs   = {f.pid: RemoteInput() for f in fighters if f.pid != 0}
    local    = LocalInput()
    title    = f"FILE SMASH  —  Sala {pretty_code(sess.display_code)}  —  {len(fighters)} jugadores"
    big      = get_font("segoeui", 48, True)
    st       = {"prev": None, "frame": 0}
    AUDIO_MGR.sink = []

    def net_events():
        for e in sess.pump():
            if e[0] == "input" and e[1] in inputs:
                inputs[e[1]].feed(e[2])
            elif e[0] == "peer_leave" and e[1] in by_pid:
                by_pid[e[1]].alive = False
            elif e[0] == "closed":
                return False
        return sess.status == "lobby"

    def send_snapshot():
        cur = [ser_fighter(f) for f in fighters]
        prev = st["prev"]
        if prev is None:
            delta = cur
        else:
            delta = [{k: v for k, v in c.items() if p.get(k) != v} for c, p in zip(cur, prev)]
        st["prev"] = cur
        sfx = list(AUDIO_MGR.sink[:12])
        del AUDIO_MGR.sink[:]
        pkt = {"fr": st["frame"], "f": delta, "sfx": sfx}
        sess.net.send(zlib.compress(json.dumps(pkt, separators=(",", ":")).encode(), 1))

    def draw_all(extra=None):
        draw_stage(screen, plats)
        for f in fighters:
            f.draw(screen)
        draw_hud(screen, fighters, 1, 1, title=title)
        if sess.stake_lost:
            _draw_banner(screen, f"Tu archivo «{sess.me['name'][:30]}» fue BORRADO", C_RED, 110)
        if extra:
            extra()

    def abort():
        sess.send_all({"t": "end", "winner": -2})
        AUDIO_MGR.sink = None
        AUDIO_MGR.stop_music()
        return None

    # Cuenta regresiva
    for n in ["3", "2", "1", "¡PELEA!"]:
        sess.send_all({"t": "cd", "n": n})
        for _ in range(FPS if n != "¡PELEA!" else FPS // 2):
            if not net_events():
                AUDIO_MGR.sink = None
                return None
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    return abort()

            def cd_lbl(n=n):
                lbl = big.render(n, True, C_YELLOW)
                screen.blit(lbl, lbl.get_rect(center=(WIN_W // 2, WIN_H // 2)))
            draw_all(cd_lbl)
            if st["frame"] % NET_TICK == 0:
                send_snapshot()
            st["frame"] += 1
            pygame.display.flip()
            clock.tick(FPS)

    winner = None
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return abort()
            local.on_event(ev)
        lmask, ledges = input_fn(st["frame"]) if input_fn else local.read()
        if not net_events():
            AUDIO_MGR.sink = None
            return None

        for f in fighters:
            if not f.alive:
                continue
            if f.pid == 0:
                mask, edges = lmask, ledges
            else:
                ri = inputs[f.pid]
                mask, edges = ri.mask, ri.take_edges()
            if EDGE_JUMP in edges:
                f.request_jump()
            f.update(fighters, plats, MaskKeys(mask), EDGE_X_DOWN in edges, EDGE_X_UP in edges)
            f.resolve_normal_attack(fighters)
            if f.kirby:
                mhb, mpow = f.kirby.get_hammer_hitbox_and_power()
                if mhb:
                    for other in fighters:
                        if other is f or not other.alive:
                            continue
                        if mhb.colliderect(other.rect):
                            d = 1 if other.rect.centerx > f.rect.centerx else -1
                            other.receive_hit(mpow, d)
                            AUDIO_MGR.play("hit")
            if f.is_out_of_bounds():
                f.alive = False
                AUDIO_MGR.play("ko")
                if f.pid == 0 and MP_STAKES and delete_stake_file(sess.me["path"]):
                    sess.stake_lost = True      # el host perdio: su archivo se borra

        if st["frame"] % NET_TICK == 0:
            send_snapshot()
        draw_all()
        st["frame"] += 1

        alive = [f for f in fighters if f.alive]
        if len(alive) <= 1 or (max_frames and st["frame"] >= max_frames):
            winner = alive[0] if len(alive) == 1 else None
            break
        pygame.display.flip()
        clock.tick(FPS)

    send_snapshot()
    sess.send_all({"t": "end", "winner": winner.pid if winner else -1})
    for _ in range(FPS * 2):
        net_events()
        msg = f"{winner.name[:40]}  GANA!" if winner else "Empate"
        draw_all(lambda: _draw_banner(screen, msg))
        pygame.display.flip()
        clock.tick(FPS)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
    AUDIO_MGR.sink = None
    AUDIO_MGR.stop_music()
    return winner.pid if winner else None


def _apply_snapshot(fighters, data):
    try:
        pkt = json.loads(_safe_decompress(data))
    except Exception:
        return []
    for f, d in zip(fighters, pkt.get("f", [])):
        apply_fighter(f, d)
        if "rect" in d:                      # posicion real; el dibujo la suaviza aparte
            f._tx, f._ty = f.rect.x, f.rect.y
    return pkt.get("sfx", [])


def run_mp_client_match(screen, clock, sess, start_msg, input_fn=None, max_frames=None):
    """Pelea vista desde un jugador (no simula: manda sus teclas y dibuja lo que manda el host).
    Devuelve 'done', 'left' o 'closed'."""
    plist    = start_msg["players"]
    plats    = [pygame.Rect(*r) for r in start_msg["plats"]]
    sprites  = {p["pid"]: decode_sprite(p["spr"], p["name"]) for p in plist}
    fighters = _build_fighters(plist, plats, sprites, sess.pid, False)
    for f in fighters:
        f._tx, f._ty = f.rect.x, f.rect.y
        f._px, f._py = float(f.rect.x), float(f.rect.y)
    mine     = next((f for f in fighters if f.pid == sess.pid), None)
    sess.last_fighters = fighters      # (para pruebas / depuracion)
    AUDIO_MGR.play_music("music_battle")
    local    = LocalInput()
    big      = get_font("segoeui", 48, True)
    title    = f"FILE SMASH  —  Sala {pretty_code(sess.display_code or sess.code)}  —  {len(fighters)} jugadores"
    cd_text, cd_frame = "", -999
    sess.stake_lost = False
    stakes_on = bool(start_msg.get("stakes")) and MP_STAKES
    fighting, lost_done = False, False
    end_msg, end_frames = None, 0
    frame, last_mask, last_send = 0, -1, -99

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                if stakes_on and fighting and mine is not None and mine.alive and end_msg is None:
                    if not confirm_modal(
                            screen, clock,
                            ["¿SALIR DE LA PELEA?", "",
                             "Salir ahora cuenta como derrota:",
                             f"tu archivo «{sess.me['name'][:40]}» se BORRARA para siempre."], C_RED,
                            f"{key_label('confirm')}: salir y perder", f"{key_label('back')}: seguir peleando"):
                        continue
                    if delete_stake_file(sess.me["path"]):
                        sess.stake_lost = True
                sess.close()
                sess.status = "closed"
                AUDIO_MGR.stop_music()
                if ev.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                return "left"
            local.on_event(ev)
        mask, edges = input_fn(frame) if input_fn else local.read()
        if edges or mask != last_mask or frame - last_send >= 10:
            sess.net.send({"t": "in", "k": mask, "e": edges})
            last_mask, last_send = mask, frame

        for e in sess.pump():
            if e[0] == "snap":
                for k in _apply_snapshot(fighters, e[1])[:12]:
                    AUDIO_MGR.play(k)
            elif e[0] == "cd":
                cd_text, cd_frame = e[1].get("n", ""), frame
                if cd_text.startswith("¡"):
                    fighting = True
            elif e[0] == "end" and end_msg is None:
                end_msg = e[1]
            elif e[0] in ("host_left", "closed"):
                AUDIO_MGR.stop_music()
                # si la pelea ya habia terminado, no es un error: el host solo cerro despues
                return "done" if end_msg is not None else "closed"

        # Si te eliminaron, tu archivo apostado se borra (solo si la pelea no se cancelo)
        if (stakes_on and fighting and not lost_done and mine is not None and not mine.alive
                and (end_msg is None or end_msg.get("winner") != -2)):
            lost_done = True
            if delete_stake_file(sess.me["path"]):
                sess.stake_lost = True

        # suavizado entre snapshots (el host manda 30/s, dibujamos a 60/s)
        for f in fighters:
            tx, ty = getattr(f, "_tx", f.rect.x), getattr(f, "_ty", f.rect.y)
            if abs(tx - f._px) > 80 or abs(ty - f._py) > 80:
                f._px, f._py = float(tx), float(ty)
            else:
                f._px += (tx - f._px) * 0.5
                f._py += (ty - f._py) * 0.5
            f.rect.topleft = (round(f._px), round(f._py))

        draw_stage(screen, plats)
        for f in fighters:
            f.draw(screen)
        draw_hud(screen, fighters, 1, 1, title=title)
        if sess.stake_lost:
            _draw_banner(screen, f"Tu archivo «{sess.me['name'][:30]}» fue BORRADO", C_RED, 110)
        if cd_text and frame - cd_frame < (45 if cd_text.startswith("¡") else 55):
            lbl = big.render(cd_text, True, C_YELLOW)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W // 2, WIN_H // 2)))
        if mine is not None and not mine.alive and end_msg is None:
            _draw_banner(screen, "ELIMINADO - mirando la pelea (ESC para salir)", C_RED, 70)
        if end_msg is not None:
            w = end_msg.get("winner", -1)
            wf = next((f for f in fighters if f.pid == w), None)
            if w == -2:
                _draw_banner(screen, "El host cancelo la partida")
            elif wf is not None:
                _draw_banner(screen, f"{wf.name[:40]}  GANA!" + ("   (conservas tu archivo)"
                                                                if (wf.pid == sess.pid and stakes_on) else ""))
            else:
                _draw_banner(screen, "Empate")
            end_frames += 1
            if end_frames > FPS * 2:
                AUDIO_MGR.stop_music()
                return "done"
        pygame.display.flip()
        clock.tick(FPS)
        frame += 1
        if max_frames and frame >= max_frames:
            return "timeout"


# ═══════════════════════ MULTIJUGADOR: PANTALLAS ═══════════════════════

def _stat_bar(surface, x, y, label, value, lo, hi, col):
    font = get_font("consolas", 12)
    lbl = font.render(f"{label} x{value:.2f}", True, C_WHITE)
    surface.blit(lbl, (x, y))
    pygame.draw.rect(surface, (50, 50, 50), (x + 130, y + 3, 150, 9), border_radius=3)
    frac = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    pygame.draw.rect(surface, col, (x + 130, y + 3, int(150 * frac), 9), border_radius=3)


def mp_message(screen, clock, text, secs=2.5, color=C_YELLOW):
    font = get_font("segoeui", 20, True)
    for _ in range(int(secs * FPS)):
        screen.fill(C_BG)
        lines = text.split("\n") if "\n" in text else [text[i:i + 80] for i in range(0, len(text), 80)]
        for i, ln in enumerate(lines):
            lbl = font.render(ln, True, color)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W // 2, WIN_H // 2 - 20 + i * 28)))
        pygame.display.flip()
        clock.tick(FPS)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                return


def mp_pick_screen(screen, clock, archivos):
    """Elige TU archivo y TU personaje para el multijugador."""
    font_t  = get_font("segoeui", 28, True)
    font_b  = get_font("segoeui", 18, True)
    font_s  = get_font("segoeui", 14)
    font_xs = get_font("consolas", 12)
    sel, scroll, ci, VIS = 0, 0, 0, 11
    while True:
        screen.fill(C_BG)
        t = font_t.render("MULTIJUGADOR  —  elige tu archivo y tu personaje", True, C_YELLOW)
        screen.blit(t, t.get_rect(center=(WIN_W // 2, 34)))
        h = font_xs.render(f"↑↓ archivo   ←→ personaje   {key_label('confirm')} continuar   {key_label('back')} volver",
                           True, C_CYAN)
        screen.blit(h, h.get_rect(center=(WIN_W // 2, 68)))

        for i, path in enumerate(archivos[scroll:scroll + VIS]):
            idx = scroll + i
            row = pygame.Rect(40, 96 + i * 30, 540, 28)
            pygame.draw.rect(screen, (40, 60, 90) if idx == sel else (25, 25, 40), row, border_radius=4)
            if idx == sel:
                pygame.draw.rect(screen, C_YELLOW, row, 2, border_radius=4)
            name = os.path.basename(path)
            pygame.draw.rect(screen, make_color_for(name), (row.x + 6, row.y + 7, 14, 14), border_radius=3)
            screen.blit(font_s.render(name[:48], True, C_WHITE), (row.x + 28, row.y + 5))
            try:
                sz = size_str(os.path.getsize(path))
            except OSError:
                sz = "?"
            sl = font_xs.render(sz, True, C_GRAY)
            screen.blit(sl, (row.right - sl.get_width() - 8, row.y + 8))

        path = archivos[sel]
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 1
        prof = file_profile(size)
        px = 610
        screen.blit(font_b.render("TU ARCHIVO", True, C_ORANGE), (px, 96))
        screen.blit(font_s.render(os.path.basename(path)[:38], True, C_WHITE), (px, 122))
        screen.blit(font_s.render(size_str(size), True, C_GRAY), (px, 142))
        _stat_bar(screen, px, 172, "Velocidad", prof["speed"], 0.75, 1.30, C_CYAN)
        _stat_bar(screen, px, 192, "Peso     ", prof["weight"], 0.70, 1.50, C_YELLOW)
        _stat_bar(screen, px, 212, "Daño     ", prof["dmg"], 0.75, 1.35, C_RED)
        _stat_bar(screen, px, 232, "Ataque   ", prof["atk"], 0.70, 1.35, C_GREEN)
        screen.blit(font_b.render("PERSONAJE", True, C_ORANGE), (px, 276))
        ch = font_t.render(f"<  {CHARACTERS[ci].upper()}  >", True, C_PINK)
        screen.blit(ch, (px, 304))

        for i, line in enumerate(HAB_INFO[CHARACTERS[ci]]):
            hl = font_xs.render(line, True, C_PINK)
            screen.blit(hl, hl.get_rect(center=(WIN_W // 2, 440 + i * 16)))
        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if is_back(ev):
                    return None
                if is_confirm(ev):
                    return archivos[sel], CHARACTERS[ci]
                if ev.key == pygame.K_DOWN:
                    sel = (sel + 1) % len(archivos)
                if ev.key == pygame.K_UP:
                    sel = (sel - 1) % len(archivos)
                if ev.key == pygame.K_RIGHT:
                    ci = (ci + 1) % len(CHARACTERS)
                if ev.key == pygame.K_LEFT:
                    ci = (ci - 1) % len(CHARACTERS)
                if sel < scroll:
                    scroll = sel
                elif sel >= scroll + VIS:
                    scroll = sel - VIS + 1
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for i in range(min(VIS, len(archivos) - scroll)):
                    if pygame.Rect(40, 96 + i * 30, 540, 28).collidepoint(ev.pos):
                        sel = scroll + i
            if ev.type == pygame.MOUSEWHEEL:
                scroll = max(0, min(scroll - ev.y, max(0, len(archivos) - VIS)))


def mp_mode_screen(screen, clock):
    font_t = get_font("segoeui", 28, True)
    font_b = get_font("segoeui", 20, True)
    font_s = get_font("segoeui", 14)
    opts = [
        ("host_online", "1   CREAR SALA ONLINE", "Usa el servidor configurado en SERVER_URL" if SERVER_URL
         else "(!) Falta configurar SERVER_URL (ver RELAYSERV.py)", bool(SERVER_URL), C_ORANGE),
        ("host_lan", "2   CREAR SALA EN RED LOCAL (LAN)", "Para jugar en la misma casa / wifi, sin servidor", True, C_GREEN),
        ("join", "3   UNIRSE A UNA SALA", "Escribe el codigo que te paso el host", True, C_CYAN),
    ]
    rects = [pygame.Rect(WIN_W // 2 - 280, 150 + i * 105, 560, 85) for i in range(3)]
    while True:
        screen.fill(C_BG)
        t = font_t.render("MULTIJUGADOR", True, C_YELLOW)
        screen.blit(t, t.get_rect(center=(WIN_W // 2, 60)))
        for rect, (key, txt, sub, ok, col) in zip(rects, opts):
            pygame.draw.rect(screen, col if ok else (60, 60, 70), rect, border_radius=10)
            pygame.draw.rect(screen, C_YELLOW if ok else C_GRAY, rect, 2, border_radius=10)
            a = font_b.render(txt, True, C_DARK)
            b = font_s.render(sub, True, C_DARK)
            screen.blit(a, a.get_rect(center=(rect.centerx, rect.y + 28)))
            screen.blit(b, b.get_rect(center=(rect.centerx, rect.y + 58)))
        hint = font_s.render(f"{key_label('back')}: volver", True, C_GRAY)
        screen.blit(hint, hint.get_rect(center=(WIN_W // 2, WIN_H - 30)))
        pygame.display.flip()
        clock.tick(FPS)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if is_back(ev):
                    return None
                for k, (key, _t, _s, ok, _c) in zip((pygame.K_1, pygame.K_2, pygame.K_3), opts):
                    if ev.key == k and ok:
                        return key
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for rect, (key, _t, _s, ok, _c) in zip(rects, opts):
                    if rect.collidepoint(ev.pos) and ok:
                        return key


def mp_code_input(screen, clock):
    font_t = get_font("segoeui", 28, True)
    font_c = get_font("consolas", 40, True)
    font_s = get_font("segoeui", 14)
    text = ""
    while True:
        screen.fill(C_BG)
        t = font_t.render("Escribe el codigo de la sala", True, C_YELLOW)
        screen.blit(t, t.get_rect(center=(WIN_W // 2, 140)))
        box = pygame.Rect(WIN_W // 2 - 220, 220, 440, 80)
        pygame.draw.rect(screen, C_DARK, box, border_radius=8)
        pygame.draw.rect(screen, C_CYAN, box, 2, border_radius=8)
        c = font_c.render(text + ("_" if (pygame.time.get_ticks() // 500) % 2 == 0 else " "), True, C_WHITE)
        screen.blit(c, c.get_rect(center=box.center))
        h = font_s.render("Online: 5 letras (ej. K7QD2)   |   LAN: 8 caracteres (ej. C0A8-010A)   |   ENTER unirse   ESC volver",
                          True, C_GRAY)
        screen.blit(h, h.get_rect(center=(WIN_W // 2, 340)))
        pygame.display.flip()
        clock.tick(FPS)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and len(text.replace("-", "")) >= 4:
                    return text
                if ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                elif ev.unicode and (ev.unicode.isalnum() or ev.unicode == "-") and len(text) < 12:
                    text += ev.unicode.upper()


def mp_lobby(screen, clock, sess):
    font_t  = get_font("segoeui", 28, True)
    font_b  = get_font("segoeui", 18, True)
    font_s  = get_font("segoeui", 14)
    font_c  = get_font("consolas", 44, True)
    while True:
        for e in sess.pump():
            if e[0] == "start" and sess.role == "client":
                res = run_mp_client_match(screen, clock, sess, e[1])
                AUDIO_MGR.play_music("music_menu")
                if res == "left":
                    return
                if res == "closed":
                    mp_message(screen, clock, "El host cerro la sala", 2.5, C_RED)
                    return
                if not _after_match(screen, clock, sess):
                    return
            elif e[0] in ("host_left", "closed"):
                mp_message(screen, clock, "La sala se cerro (el host se fue o se perdio la conexion)", 3, C_RED)
                return
        if sess.status == "error":
            mp_message(screen, clock, sess.error, 4, C_RED)
            return
        if sess.status == "closed":
            mp_message(screen, clock, "La sala se cerro (el host se fue o se perdio la conexion)", 3, C_RED)
            return

        screen.fill(C_BG)
        t = font_t.render("SALA MULTIJUGADOR", True, C_YELLOW)
        screen.blit(t, t.get_rect(center=(WIN_W // 2, 40)))
        if sess.status == "connecting":
            dots = "." * (1 + (pygame.time.get_ticks() // 400) % 3)
            lbl = font_b.render("Conectando" + dots, True, C_CYAN)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W // 2, 200)))
            note = font_s.render("(un servidor gratis de Render puede tardar ~1 minuto en despertar)", True, C_GRAY)
            screen.blit(note, note.get_rect(center=(WIN_W // 2, 235)))
        else:
            if sess.role == "host":
                code = pretty_code(sess.display_code or sess.code)
                kind = "red local (misma wifi)" if lan_decode(sess.display_code or "") else "online"
                lbl_c = font_s.render(f"Codigo de la sala ({kind}):", True, C_GRAY)
                screen.blit(lbl_c, lbl_c.get_rect(center=(WIN_W // 2, 86)))
                c = font_c.render(code, True, C_CYAN)
                screen.blit(c, c.get_rect(center=(WIN_W // 2, 130)))
            for i, (pid, p) in enumerate(sorted(sess.players.items())):
                row = pygame.Rect(WIN_W // 2 - 280, 185 + i * 40, 560, 36)
                pygame.draw.rect(screen, (25, 25, 40), row, border_radius=6)
                if pid == sess.pid:
                    pygame.draw.rect(screen, C_YELLOW, row, 2, border_radius=6)
                surf = p.get("surf")
                if surf is not None:
                    screen.blit(pygame.transform.scale(surf, (28, 28)), (row.x + 6, row.y + 4))
                else:
                    pygame.draw.rect(screen, make_color_for(p["name"]), (row.x + 10, row.y + 8, 20, 20), border_radius=4)
                tag = "  (host)" if pid == 0 else ""
                tag += "  ← tu" if pid == sess.pid else ""
                screen.blit(font_s.render(p["name"][:34] + tag, True, C_WHITE), (row.x + 44, row.y + 9))
                right = font_s.render(f"{p['char'].upper()}  ·  {size_str(p['size'])}", True, C_PINK)
                screen.blit(right, (row.right - right.get_width() - 10, row.y + 9))
            n = len(sess.players)
            if sess.role == "host":
                msg = (f"{key_label('confirm')}: empezar ({n}/{MAX_PLAYERS} jugadores)   ·   {key_label('back')}: cerrar sala"
                       if n >= 2 else
                       f"Esperando jugadores...  (necesitas al menos 2)   ·   {key_label('back')}: cerrar sala")
            else:
                msg = f"Esperando a que el host empiece la partida...   ·   {key_label('back')}: salir"
            hl = font_s.render(msg, True, C_ORANGE)
            screen.blit(hl, hl.get_rect(center=(WIN_W // 2, WIN_H - 30)))
            if MP_STAKES and (sess.role == "host" or sess.stakes):
                wl = font_s.render("APUESTA ACTIVA: el que pierda BORRA su archivo para siempre", True, C_RED)
                screen.blit(wl, wl.get_rect(center=(WIN_W // 2, WIN_H - 62)))
        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if is_back(ev):
                    return
                if (is_confirm(ev) and sess.role == "host"
                        and sess.status == "lobby" and len(sess.players) >= 2):
                    plist, plats = sess.host_start()
                    run_mp_host_match(screen, clock, sess, plist, plats)
                    sess.after_match()
                    AUDIO_MGR.play_music("music_menu")
                    if not _after_match(screen, clock, sess):
                        return


def multiplayer_menu(screen, clock):
    if not HAS_WS:
        mp_message(screen, clock, "Falta la libreria de red.\nInstalala con:  pip install websockets", 4, C_RED)
        return
    me = None
    while True:
        if me is None or not os.path.exists(me["path"]):
            files = list_pvp_files()
            if not files:
                mp_message(screen, clock, "No hay archivos en la carpeta PVP.", 3, C_RED)
                return
            pick = choose_file_screen(screen, clock, files, "ONLINE BATTLE")
            if not pick:
                return
            if MP_STAKES and not mp_confirm_stake(screen, clock, pick[0]):
                continue                                   # no acepto la apuesta: elige otro
            me = make_player_info(*pick)
        choice = mp_mode_screen(screen, clock)
        if choice is None:
            return
        sess = MPSession(me)
        if choice == "join":
            code = mp_code_input(screen, clock)
            if code is None:
                continue
            sess.join(code)
        else:
            sess.host(lan=(choice == "host_lan"))
        mp_lobby(screen, clock, sess)
        me = sess.me                                       # por si cambiaste de archivo dentro de la sala
        sess.close()
        AUDIO_MGR.play_music("music_menu")


# ═══════════════════════ CONTROLES DE MENU, AVISOS Y APUESTA ═══════════════════════

# Teclas de los menus. Por defecto: Z = continuar, X = volver.
# (Enter y Esc siguen funcionando tambien. Mas adelante se podran cambiar en Configuracion.)
MENU_KEYS = {"confirm": pygame.K_z, "back": pygame.K_x}


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for k in MENU_KEYS:
            v = data.get("keys", {}).get(k)
            if isinstance(v, int):
                MENU_KEYS[k] = v
    except Exception:
        pass


def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump({"keys": MENU_KEYS}, fh)
    except Exception:
        pass


def key_label(which):
    return pygame.key.name(MENU_KEYS[which]).upper()


def is_confirm(ev):
    return ev.type == pygame.KEYDOWN and ev.key in (MENU_KEYS["confirm"], pygame.K_RETURN, pygame.K_KP_ENTER)


def is_back(ev):
    return ev.type == pygame.KEYDOWN and ev.key in (MENU_KEYS["back"], pygame.K_ESCAPE)


def list_pvp_files():
    try:
        return sorted(os.path.join(PVP_FOLDER, f) for f in os.listdir(PVP_FOLDER)
                      if os.path.isfile(os.path.join(PVP_FOLDER, f)))
    except OSError:
        return []


def delete_stake_file(path):
    """Borra PARA SIEMPRE el archivo apostado. Solo toca archivos que estan dentro de la carpeta PVP."""
    try:
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(PVP_FOLDER) + os.sep):
            return False
        os.remove(real)
        print(f"[BORRADO] {real}")
        return True
    except OSError as e:
        print(f"[no se pudo borrar] {path}: {e}")
        return False


def confirm_modal(screen, clock, lines, color=C_RED, yes_txt=None, no_txt=None):
    """Ventana de confirmacion encima de lo que haya en pantalla. True = continuar, False = volver."""
    bg = screen.copy()
    shade = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 175))
    f1 = get_font("segoeui", 24, True)
    f2 = get_font("segoeui", 16)
    yes = yes_txt or f"{key_label('confirm')}: si"
    no  = no_txt or f"{key_label('back')}: no"
    h = 120 + 28 * len(lines)
    box = pygame.Rect(WIN_W // 2 - 400, WIN_H // 2 - h // 2, 800, h)
    while True:
        screen.blit(bg, (0, 0))
        screen.blit(shade, (0, 0))
        pygame.draw.rect(screen, C_DARK, box, border_radius=12)
        pygame.draw.rect(screen, color, box, 3, border_radius=12)
        for i, ln in enumerate(lines):
            lbl = (f1 if i == 0 else f2).render(ln, True, color if i == 0 else C_WHITE)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W // 2, box.y + 36 + i * 28)))
        hint = f2.render(f"{yes}        {no}", True, C_YELLOW)
        screen.blit(hint, hint.get_rect(center=(WIN_W // 2, box.bottom - 30)))
        pygame.display.flip()
        clock.tick(FPS)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if is_confirm(ev):
                return True
            if is_back(ev):
                return False


def mp_confirm_stake(screen, clock, path):
    name = os.path.basename(path)
    return confirm_modal(
        screen, clock,
        ["APUESTA TU ARCHIVO", "",
         f"Si pierdes, «{name[:44]}» se BORRARA de tu PC para siempre.",
         "Todos en la sala apuestan igual.  Apuesta una COPIA, nunca tu unico archivo.", ""],
        yes_txt=f"{key_label('confirm')}: acepto el riesgo", no_txt=f"{key_label('back')}: volver")


def _after_match(screen, clock, sess):
    """Si perdiste tu archivo en la pelea, tienes que apostar otro para seguir en la sala."""
    if not sess.stake_lost:
        return True
    sess.stake_lost = False
    lost = sess.me["name"]
    files = list_pvp_files()
    if not files:
        mp_message(screen, clock, f"Tu archivo «{lost}» fue BORRADO.\nYa no te quedan archivos en PVP.", 4, C_RED)
        return False
    mp_message(screen, clock, f"Tu archivo «{lost}» fue BORRADO.\nElige otro archivo para seguir en la sala.", 3, C_RED)
    pick = choose_file_screen(screen, clock, files, "ONLINE BATTLE")
    if not pick:
        return False
    if sess.stakes and MP_STAKES and not mp_confirm_stake(screen, clock, pick[0]):
        return False
    sess.change_me(make_player_info(*pick))
    return True


# ═══════════════════════ SUBMENU "FIGHT" ═══════════════════════

def mode_screen(screen, clock, n_archivos):
    AUDIO_MGR.play_music("music_menu")
    font_t = get_font("segoeui", 36, True)
    font_b = get_font("segoeui", 22, True)
    font_s = get_font("segoeui", 14)
    btn_cpu = pygame.Rect(WIN_W // 2 - 260, 190, 520, 90)
    btn_mp  = pygame.Rect(WIN_W // 2 - 260, 310, 520, 90)
    cpu_ok  = n_archivos >= 2
    mp_line = ("Hasta 8 jugadores con codigo de sala. El que pierde BORRA su archivo." if MP_STAKES
               else "Hasta 8 jugadores con codigo de sala. (modo practica: no se borra nada)")
    while True:
        screen.fill(C_BG)
        t = font_t.render("FIGHT", True, C_YELLOW)
        screen.blit(t, t.get_rect(center=(WIN_W // 2, 60)))
        for i, ln in enumerate((
                "PESADO: mas lento, ataques lentos, pega fuerte y cuesta lanzarlo.",
                "LIVIANO: mas rapido, ataques rapidos, pega menos y es facil de lanzar.")):
            sub = font_s.render(ln, True, C_GRAY)
            screen.blit(sub, sub.get_rect(center=(WIN_W // 2, 108 + i * 20)))

        for rect, txt, line2, ok, col in (
            (btn_cpu, "VS CPU", "Todos los archivos de PVP pelean. El perdedor se BORRA del disco."
             if cpu_ok else "Necesitas al menos 2 archivos en la carpeta PVP", cpu_ok, C_ORANGE),
            (btn_mp, "MULTIJUGADOR", mp_line, True, C_CYAN),
        ):
            pygame.draw.rect(screen, col if ok else (60, 60, 70), rect, border_radius=10)
            pygame.draw.rect(screen, C_YELLOW if ok else C_GRAY, rect, 2, border_radius=10)
            a = font_b.render(txt, True, C_DARK)
            b = font_s.render(line2, True, C_DARK)
            screen.blit(a, a.get_rect(center=(rect.centerx, rect.y + 32)))
            screen.blit(b, b.get_rect(center=(rect.centerx, rect.y + 62)))
        hint = font_s.render(f"1 / 2 o clic para elegir      {key_label('back')}: volver", True, C_GRAY)
        screen.blit(hint, hint.get_rect(center=(WIN_W // 2, WIN_H - 30)))
        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if is_back(ev):
                return None
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_1, pygame.K_KP1) and cpu_ok:
                    return "cpu"
                if ev.key in (pygame.K_2, pygame.K_KP2):
                    return "mp"
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if btn_cpu.collidepoint(ev.pos) and cpu_ok:
                    return "cpu"
                if btn_mp.collidepoint(ev.pos):
                    return "mp"


# ═══════════════════════ MENU PRINCIPAL Y SELECCION DE ARCHIVO (tus dibujos) ═══════════════════════
# Todo se dibuja con las medidas de tus imagenes (792 x 441) y se escala a la ventana.
# Las imagenes de fondo estan guardadas aqui dentro (UI2_IMAGES), asi que no hacen falta archivos extra.

DESIGN_W, DESIGN_H = 792, 441
UI_FONT   = "arial,liberationsans,helvetica,dejavusans"
C_NAVY    = (37, 45, 137)
C_UIGRAY  = (195, 195, 195)
C_DKGRAY  = (127, 127, 127)

UI2_IMAGES = {
    "menu_default": (
        "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",
        "d/ksy8mzNif3PIvb4MxV0DB2fXjj2csvvbS4Fq1euCoM1JtWnSnZ2rt+22kN5y1pc+NqUjzbriTJqrh6c/+rVW6nzZY3a1G1NPUq",
        "FWtcbEcetX1DBWeTeeXcufXS3uUgCJ69nvhUgU6srM1m2M3hNcTicJtfFja1/4JGnntt2bLFoktcZnXJbj57EjG8/Bmbask5NMV1",
        "S5LUFj766KNhiZTJU3uplnP1avoKnejV7osvVuiDNwW/Us9xS5Ku7Z9OMrIYR8+G5zcNjCfFTIpew7j2MldxkZ1y+szyKouroMkO",
        "np7ti4veIm1z5cnjOz84sN8dy6rzlxO1P9mROy9ddiRJpqGJZEtJsypbKqPlt7Wo5pp6Kb0xKHYzGyo8mwzIPKuVPBRgcVPkbo9s",
        "riE1XRby2389W1yt38X4x4Zr8d6zSbDs6s1vlhuwNqrbUtfeITGbzfr9mF7JiNTy0bTVe4HF2eA00HnSkF/85srTpzev7u5evfnN",
        "r6VNanWZ/W9uGhg/LWY2hdDNZe+1r17NXgMPbzy7dqeeuQoW7WBOCOTraxf/W3slYgmWVecvy0eCTndEV6699tXLjRVgL0ePbEtl",
        "sPz2FtVcU7eXAbNiN7yhvLPJpu9PDtXJYybObz9quoY4vizktn+3W1xm93/ztdNlkqf9Nlb68tiWHLw1q9tS117oL6YRqdQsIis5",
        "Aan5gdc+2jQL8cYFUjNVHWyb7jiTTbK+SLKV5N+ZqdjTfzKfXbl44cW6N0xzk514ZNsOFs7FvLJP1vNIGVSd+dquVZvZfGMNm8wj",
        "dTqTT86M5DXOI5Wegea0Jk8/3Vqq7FaLlzdoUXU09arH3fBEKGyoRoUxrp/Cs8l27vQtdWc6l17u2txeQ4wPt+EVdWv7N7wKGV6I",
        "Nk1c/lrRHPFXXjuIzeeRyj08hSUzufYOm4sXL37qU5/iFTGb7yAytwIng8Vu45y39i6nUjp1kg2Yvge481KyyOHmRdbjaS7mZ8jj",
        "8HCRq7jh2dnlzezJHbLBDm6+BSx7q1Wq6nzmzmrq73JPgssNZbUu736rlKp4edMW1VRTtwyqmBa7+Q2VOZvuvHT52euZE8f5efNr",
        "dV5D3F4Wctu/2y3e2ltdRDo8vL1tL++8dLnapdJ13QIAAAAAmPHEE0/89m//NhEpAAAAANgmUuPxeDweUxEAAABQnZ/97GeDeksM",
        "ESkAAACAspw9e/bs2bPUAwAAAFRnNBo9/vjj5EgBAAAAwFaTCsMwRKcAAADAAckwFxEpAAAAANjCOIoiagEAAACcEEXRoEa6iEgB",
        "AAAAlCRIXrR3dHREXQAAAIATMnlRQRD0dU+JSAEAAACUZNzvXHoAAACA+iAiBQAAAFCS8fHxMbUAAAAATtjZ2RnUhABEpAAAAADK",
        "ihQzmwMAAIAroiiaTqcDEikOOQAAAEBJkZpMJpPJhIoAAACA6kyn0/F4PCCR4pADAAAAlOP/A/kk4CmRyOrbAAAAAElFTkSuQmCC",
    ),
    "menu_fight": (
        "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",
    ),
    "menu_online": (
        "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",
        "wN+XRAoAAACgKePRsfHoGO0AAAAARphMJiRSAAAAAFBnjdGJmYjIezQFAAAAGGBra2s4X5ZECgAAAKAhk633piIyoyUAAACgNceP",
        "H9/b2xuQSD2UhLUOAAAA0AC69gAAAMAYs9lsOp0iUgAAAAAAAAAA0CFbW1uMIwUAAAAAiBQAAAB0xXg8fuyxxxApAAAAADDPpRtJ",
        "ITtXz4mcu7qT/b7k3KUbOzsHb9u5cfXSufWp3bhUOJPFy2WzXJ/TwSyvLme4PmGFRaqbyMp3XC7a6lsKv9W5Szd2Dma5MkfNL3ju",
        "0tXc8u/s3Lh07pwoTu2qQoNXTKDyDTs7Ny6dU95m8u8u2QyU1sjy1dWWyq0Yk1+ndCWWfgMf9hdTu0ZuzvkZHbx9ba/ZaHCVBhWl",
        "TVR981DZp4oXRqnV9XaKwg3DTFNUHH9qqF3dVUe/osUr2ayK9ods3rl5ZDPQPRSrHWagPYcPHx6Px9RImeLc1Z3ktWsXtrezV7a3",
        "L7x47bXa43m7uf7u55YzvPDCpYaLVDmRDS5cq947z13dee3ahe2DWb547bVm+/O5qzuvXXsxt/zb2xeuvWa5RdXY3r6g8a303l2+",
        "Ru689Oc3RUS2X/zypYNG+pMLIiK7r7x83dzXMbcS3dpfbOwa25/73exDv/bxbcUGN96gapuHzX1KezO3tWobb7r1q7vu6FfQJsUb",
        "9Z03dkREtj/+axvzPvPs8t3nnj0jIrL71g/FxMIA9ChSNy9Hq5x56c7m3vv1F7dFZPfm5efSNz13+ebu+lGtnusXlzN57pXd9AD4",
        "XPlcFzvf7s2bu5u7vvIiVU1Ef/9dHA8Wc33u8k0RkQt/sjySqH/B0uXffvHrSlN7o8UqjqLo4vXSNyxmdvCtqib43OXad6uv1usX",
        "Vxs0a6RX/jDXeq2/Ts1K9HZ/sbNrHJwML71wQaVNlg3+wiWDm6jK5qGyTzVdJK2donYVNW6KNpuu0uqutZf84lU07w/f2l2xpgMH",
        "z8x8+V2+8407Da9qwTrT6XQ+nyNSRrj05Re3ReTm5TMXry+2+TvXL/7hK7u7N1+53CIpUNvxv/Pyy9/Z2PWVF6lqIqUqVX9geuuH",
        "d0TkzvVv3Vw917Rr0jOXb2qfbM2zvPRXe/P1ZVCg2gaVa+T6y6/sZk2waKRVjTL4dQpX4uIM4OH+Yn7XSE+6yz+kHnXzZt3Gcecb",
        "31k9iZqjcvOwuk9p7RT2aXD8UT0SalwSpdtVYfMuNoLlkuW3neVrC7faeeOO9qHYwE4K0LFILRLYm9+6vnZoOXPm4kvX71ibbXrB",
        "svPGncVOmdv1lRepaiKF11vprl56BbuMrF98La2+WGQGFzXPjotr+/Xll8WB0cIpSKfhF/0llUe47M2Xlr0rJQG9zmoVkTsvpYfm",
        "C39y40Y64Zt//tIds19HYSWqfhuH9hcbu8Zbb+1km2M64d233qrdImqThjY+U7p52N2ntHYKixc5jY8/Kqu77uinY82LJU3nstx2",
        "Xv7WzbXXNteX+sK02UlBjfF4jEgpceFaXRFreuWgttWuTS25dqGlR9381vVsbz3Y9VUXqXIihXxrec1bsv8uuxcW1RflJagKFCx/",
        "eqmlkXCpNPj6ezbW8uobXltc6JdnJ7n3v3btxW0d3alfI4tr/+0LF9J8YeMk0f7rVK3ExQnAu/1FrOwa3/jWzUVnzDLQ+MYbNd8i",
        "3SI0Y8Tadaq6eZjYp1rvFEp3AzRriqbHH7XVXXf0K1e70tTozLO5bedO+uKFFy4pbKgVC1O3kwK4l0htXpztVNxcYzaPWlyv1ElQ",
        "ySLpTWT1mre0M+D6xei5y6/cXGTL29sXrjlRIG6O3ZuvXH5OvcJjd/fmK5efU8zklNZIdrIo0igzX6duJZoMHjrZX3Tnrrpr/PCt",
        "3dSk0vOecrtsf85a/7TZzcPOTmGRRscf1dVde/TTCM+yzr2DMGz54plnzy0CqaoNqm5hek4HB8GxY8eiKEKk6lmrbSw4VOhc0a1X",
        "Sl5uWFiwvMljeXmWXhBmu77aItVMpHz/TcshLly78ULJO66/dPFM4xLig5PN5vLrpBnKDb5Zvrq2ltM3PLe81j3zcZ2Z6nRYqa6R",
        "xdVscTsY+jplK7Gm/sLN/UV37sq7Rnrm2/74l9Mil+J+mLW67Muv7Ipsa1UK165T1c2jZp+qWrlrk2u1U0TNnUuhKbSPPxpHwvqj",
        "39qkUyEqz6ouvPDljx9I3GJ7+tzvrpid9qGYIinwLpFa7hDLur87L50xdNCv3fE3WOz6SotUN5H6a94LF9Z6WtbGL8mKLXUrMBZ1",
        "G+ullP0WYty5fjG9N2n7wrWvW8nYmq8Rk1+nZiXeeWOnXfVFD/uL7tw1VkQ6vXRPUGuW7P6Dbkv9dPap1SUrd4EudgodGh5/9Pa7",
        "0qNfIRUl4wvbSaezVKZ0e9p+8UW1K8aShWm9k4IaH3zwASJl7BCVdVYf9Mefu3T1hTOWPergZu+DM8Fi11dYpPqJKOy/pQfrdK7L",
        "wlpt9VnebpNb/nOXbny9thDD9ll4EaY3u2G8/Wrt5OvUrcTrF1t24XS+v+jOXWtFLJpL1MvHz1194UIPG6/KPpUVa3/96sF70rv9",
        "SvdhuztFQ1nUOf5o73clR7/NCV+6unPtQukha1mIvhr3HWxPaofN4oVpvZOCErPZLOwROI1f3awfC1dHpj1XOnzv6ri31SM1l09f",
        "5Y9r06pZpPqJ1Aw6nCsuKX61srC08guWT6nkEwVTu9RuZPPyoZaz5SpYktoRhUvnuHP1nNpqrWg9Y1+naiUu/lY6srkr+0vVBtZ6",
        "11j8nr5jbUzq/J8q1kj98Ow7V881HLy99Lur7FNlA5dfPVe/QervFIVjdrdoCoVNd2PYVdXVXX30K1+88hWVfaZ4DRwMR695KC7d",
        "ScEKjGxu7Np+tcRRljXG0Rnz5Z5lA7UtL8cWF1HVi6Q4EZU4Y+3VM89dvrm7m5/nc42uje68dOa5y6+sTeryc71fZ915KR16x/QF",
        "+K+1XiPGvo65lejC/qI7d91dYxks1NSz5NndVb//wPDKrt2nrl9cfYvI7u7Nuv3O1k7R7BtqbbrNjoTFR7/N9Vx9yMrSp5XoaVng",
        "pNw3p7YwYIETJ0488cQTtAMABBwqh3XDKLBJgHsiNZxECgCGxbmrO5w0gU0C7HH69Onf/u3fRqQAIEgu3di5wTkT2CQAkQIAAABw",
        "jslk8ju/8zsUmwMAAAAAAAAAQFeMx+Mnn3ySRAoAAAAAAAAAALriyJEjwoCcAAAAAIBIAQAAQHfEcTwaDcguECkAAACAhkQ0AQAA",
        "AJhlrS4qioL1DRIpAAAAAEQKAAAAAJECAAAA8IIJTQAAAACmOHz4cBzHw/m+JFIAAAAATUUqhYYAAACA9sRxPJ1OByRSrHIAAACA",
        "hiK1tbW1tbVFQwAAAEB7ptPpZDKgCmwSKQAAAICG/H/iEZqwbpte7AAAAABJRU5ErkJggg==",
    ),
    "choice_bg": (
        "iVBORw0KGgoAAAANSUhEUgAAAxgAAAG5CAIAAACCwAVRAAAHkklEQVR42u3dPWobQRiAYUkIl2kCJgaVqnIBNzmBQRBIn4PkLmly",
        "BYHvkBOkSRlwGrtwaQhOYVAU2d6/mZ2dmX2eKiSSLK0d/PJ9q9XydrNd1OLtr5+HP9f0ul58gYtvvwt9FY8f3y2o2I83jgGvur5w",
        "DEjj7uufNF9oXeXhU1EAMKugmcra91hFASBomHtIHVKjynEUAIIGIUVQIy4WxlFAsTI7QUrQUEBIne12XW72sN/7TsykopxpDgga",
        "hFScfjq+fWBLzWKvZxZF/rxlr+ig+XQ+8lcQTAip2Al1ckejqdcCERA0QM0hNTihwnOq1tpwahRoGqD+kIqSUCcPOGw0VevFRVUU",
        "ZRhzrydogDpDKnpFBbbUGE944oWjiiInd+9dXgQgUkiNVFG9dN/rBZ6/lbKrei8rPxfzVril/3N5cLk1gChWw8rjbLfLoaK6/2KI",
        "+GzHfuGWegBQinVzLry4YkuTUCNt90IeM8ELV1EAUENIFaHvCiywzB72+4a+jGxQRT1+dxUfmiwv7x0EgIhWrbc4GcPkttF7UscJ",
        "H64aBQBlWXeMp6cBTOKKSjH4ybKibjfbxZcPPe7rBxkA8gmp1rTKqjwqGEedVhQAUFNIhTuZLeW5Ipy8JlUUAAipV/vp+O/Tt1Se",
        "9XY8jnKaFOl/6gCIGVJRamPsc5uq2ev5fQYA5VqN8aDzOUNcRQHAnMVf7XWsqJC5l/6gKtcX0R7q6sbhBEgp8kQq8Syq6L2eHASA",
        "2kIqZFDUvaJKfMueigIAWkIqQUWlT5Dcuk1F8Z+rmzgrOXs9gHJDKn3WuOQSteWUigKYZ0h5m153xlHEjyEVBZBDSOV/6lLpFaKi",
        "iJ9EKgogk5BKYM57PRVF/DBSUQCTCr2OVK+lXt+KsjFkvi3VenEpCQWQgdCJVPc2Cp9FDftYmEz2lcZRACCkRu+tg5rGUSqK3poH",
        "TsZRALmF1ODJTesdZ375TRVF5JZSUQDZ+HeO1PMJUJQAGvYgz5/MsL0e1NlSAOQWUl1qJk1F1cQ4CgAqtsrwOTWMo1QUACCkelTU",
        "MXs9AEBIla3L0tM4CgCE1OjB0Xr7EotERQGAkEraUq23LGWvp6IAQEglbSmfBgMACKkhndTwrxlOd5pfi3EUAMzHevJn0HEWVcRe",
        "b/KKWl7e+5kGgGTSvWvvxWAqa6P3sN+XNTwDAEa1TDzpOVzrvNcVBAKf5OALrPfqPCEFAEIqRUt1DJSCPl9PRQHADE1wQc763qCn",
        "ogBASGVaJ5mPo1QUAAgpAACEVELGUQAgpPINlJz3eioKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAFJYPjoGAACDrBwCAAAhBQCQ1Ppus3UUAAAGMJECABBSAABCCgBASAEACCkAAIQUAICQAgAQUgAAQgoAQEgB",
        "ACCkAACEFACAkAIAEFIAAEIKAAAhBQAgpAAAhBQAgJACAEBIAQAIKQAAIQUAIKQAAIQUAABCCgBASAEACCkAACEFACCkAAAQUgAA",
        "QgoAQEgBAAgpAACEFACAkAIAEFIAAGX5C7buhoqlghgLAAAAAElFTkSuQmCC",
    ),
    "word_bg": (
        "iVBORw0KGgoAAAANSUhEUgAAAxgAAAG5CAIAAACCwAVRAAAJiElEQVR42u3dT2oTURzA8SSELl2JWOgyqx5EoRAQ3NoT9AZCVz2H",
        "K3uDAaEXqUfopu0BAloXhRhTO5k/b9689+bzWYmm+TNW8+X3m0znDyerWSnenn7c/vr+9mZWnN0X+PTlMtNX8fTp/YyC/XzjGPCq",
        "H8eOAXE8fvsV54GWRR4+FQUAkwqasSz9HasoAAQNUw+pbWoUOY4CQNAgpOjViDPjKCBfiZ0gJWjIIKSO1usmN9tUlb+JiVSUM80B",
        "QYOQCtNPu7fv2VJT2OuZRZEBH9nLOmg+vxv4EQQTQip0Qu19odHUa4EICBqg5JDqnFD9c6rU2nBqFGgaoPyQCpJQe3fYbTRV0l5P",
        "RZGfIfd6ggYoM6SCV1TPlhriCY+7cFRRJOXxdOUgAIQJqYEqqpXme72e52/F7Kq2y8r59VUu33CL6wv/6lLgcmsAYd7XupXH0Xqd",
        "QkU1f2MI+GyHfuGWegCQi2V9Lvx3xRYnoQba7vW5zwgvXEUBQAkhlYW2K7CeZbapqpq+DKtbRf2++u57mhqLy3MHASDk/6sHb7E3",
        "hklto/esjBM+XDUKAPKybBhPzwOYyBUVYfCTZkXd397Mvt50+1oAYOSQOphWSZVHAeOo/YoCAEoKqf72ZktprghHr0kVBQBC6tV+",
        "2v39+C2VZr3tjqMs6Yj/XQdAyJAKUhtDn9tUzF7P+xkA5GsxxJ1O5wxxFQUAUxZ+tdewovrMvfQHRflxHOyuzu4cToCYAk+kIs+i",
        "st7ryUEAKC2k+gyKmldUjh/ZU1EAwIGQilBR8RMktW5TUfzj7C7MSs5eDyDfkIqfNS65RGk5paIAphlSPqbXnHEU4WNIRQGkEFLp",
        "n7qUe4WoKMInkYoCSCSkIpjyXk9FET6MVBTAqPpeR6rVUq9tRdkYMt2WOnhxKQkFkIC+E6nmbdR/FtXtx8Iksq80jgIAITV4b22V",
        "NI5SUbRWP3AyjgJILaQ6T24OfuHEL7+pogjcUioKIBl/z5F6OQEKEkDd7uTlk+m214MyWwqA1EKqSc3EqaiSGEcBQMEWCT6nmnGU",
        "igIAhFSLitplrwcACKm8NVl6GkcBgJAaPDgO3j7HIlFRACCkorbUwVvmstdTUQAgpKK2lJ8GAwAIqS6dVPOnCU536l+LcRQATMdy",
        "9GfQcBaVxV5v9IpaXJ77ngaAeO+84wZTXhu9TVXlNTwDAAY1fzhZxXy87bXOW11BoOc4qvMF1lt1npACgKmJvdrbVNXReh15EBXh",
        "4VQUAEzQCBfkLO8DeioKAIRUonWS+GnmKgoAhBQAAEIqIuMoABBS6QZKyns9FQUAEzeff7hwFAAAOrDaAwAQUgAAQgoAQEgBAAgp",
        "AACEFACAkAIAEFIAAEIKAEBIAQAgpAAAhBQAgJACABBSAABCCgAAIQUAIKQAAIQUAICQAgBASAEACCkAACEFACCkAACEFAAAQgoA",
        "QEgBAAgpAAAhBQAgpAAAEFIAAEIKAEBIAQAIKQAAhBQAgJACABBSAABCCgBASAEAIKQAAIQUAICQAgAQUgAAQgoAACEFACCkAACE",
        "FACAkAIAQEgBAAgpAAAhBQAgpAAAhBQAAEIKAEBIAQAIKQAAIQUAIKQAABBSAABCCgBASAEACCkAAIQUAICQAgAQUgAAQgoAQEgB",
        "ACCkAACEFACAkAIAEFIAAEIKAAAhBQAgpAAAhBQAgJACABBSAAAIKQAAIQUAIKQAAIQUAABCCgBASAEACCkAACEFACCkAAAQUgAA",
        "QgoAQEgBAAgpAAAhBQCAkAIAEFIAAEIKAEBIAQAgpAAAhBQAgJACABBSAABCCgAAIQUAIKQAAIQUAICQAgAQUgAACCkAACEFACCk",
        "AACEFAAAQgoAQEgBAAgpAAAhBQAgpAAAEFIAAEIKAEBIAQAIKQAAIQUAgJACABBSAABCCgBASAEAIKQAAIQUAICQAgAQUgAAQgoA",
        "ACEFACCkAACEFACAkAIAEFIAAAgpAAAhBQAgpAAAhBQAgJACAEBIAQAIKQAAIQUAIKQAABBSAABCCgBASAEACCkAACEFAICQAgAQ",
        "UgAAQgoAQEgBAAgpAACEFACAkAIAEFIAAEIKAAAhBQAgpAAAhBQAgJACABBSAAAIKQAAIQUAIKQAAIQUAICQAgBASAEACCkAACEF",
        "ACCkAAAQUgAAQgoAQEgBAAgpAAAhBQCAkAIAEFIAAEIKAEBIAQAIKQAAhBQAgJACABBSAABCCgAAIQUAIKQAAIQUAICQAgAQUgAA",
        "CCkAACEFACCkAACEFACAkAIAQEgBAAgpAAAhBQAgpAAAhJRDAAAgpAAAhBQAgJACABBSAAAIKQAAIQUAIKQAAIQUAICQAgBASAEA",
        "CCkAACEFACCkAACEFAAAQgoAQEgBAAgpAAAhBQCAkAIAEFIAAEIKAEBIAQAIKQAAhBQAgJACABBSAABCCgBASAEAIKQAAIQUAICQ",
        "AgAQUgAACCkAACEFACCkAACEFACAkAIAQEgBAAgpAAAhBQAgpAAAhBQAAEIKAEBIAQAIKQAAIQUAgJACABBSAABCCgBASAEACCkA",
        "AIQUAICQAgAQUgAAQgoAQEgBACCkAACEFACAkAIAEFIAAAgpAAAhBQAgpAAAhBQAgJACAEBIAQAIKQAAIQUAIKQAAIQUAABCCgBA",
        "SAEACCkAACEFACCkAAAQUgAAQgoAQEgBAAgpAACEFACAkAIAEFIAAEIKAEBIAQAgpAAAhBQAgJACABBSAABCCgAAIQUAIKQAAIQU",
        "AICQAgBASAEACCkAACEFACCkAACEFAAAQgoAQEgBAAgpAAAhBQAgpAAAEFIAAEIKAEBIAQAIKQAAhBQAgJACABBSAABCCgBASAEA",
        "IKQAAIQUAICQAgAQUgAAQgoAACEFACCkAACEFACAkAIAQEgBAAgpAAAhBQAgpAAAhBQAAEIKAEBIAQAIKQAAIQUAIKQAABBSAABC",
        "CgBASAEACCkAACEFAICQAgAQUgAAQgoAQEgBACCkAACEFACAkAIAEFIAAEIKAAAhBQAgpAAAhBQAgJACABBSAAC0NX9yDAAAOjGR",
        "AgAQUgAAcS0fT1aOAgBAByZSAABCCgBASAEACCkAACEFAICQAgAQUgAAQgoAQEgBAAgpAACEFACAkAIAEFIAAEIKAEBIAQAgpAAA",
        "hBQAgJACABBSAAAIKQAAIQUAIKQAAIQUAICQAgBASAEACCkAACEFACCkAACEFAAAQgoAQEgBAAgpAAAhBQCAkAIAEFIAAEIKACAv",
        "fwDUy2BQN2ICBwAAAABJRU5ErkJggg==",
    ),
    "spr_bottom": (
        "iVBORw0KGgoAAAANSUhEUgAAAGUAAAAiCAYAAABGIRcbAAACEklEQVR42u2asW6DMBCGfYgnaAeWdGu3bFkZsnbNhCrxIjxAXyRS",
        "xcSaNZWydsvWsV0Y6Cu4Q+UqODbY5mwg3EmRIohsdJ//+30m0KweGcW0IqIUEBQKg4gpBerYrUsuvlfnDELODeQpbQC6CAkmpuRT",
        "+ZotgLuvT+V4Pw9PQFA8gzgeNmz7/HF1bdG7r9265OIzBhBbCDoFoSjFZXBM6aqSKq6F3v3ISlHukPY1Y4wxnif+PAX2tfUE968n",
        "p1XSFCnYrPLduuShwciQjofNPwhfMK6gNEUKwP6SbDqh64OJeZoiBSxDrs5ZayyVNwwNnyC0ntIUKTRFCrCvW6sCO3ieMJ4nVkqz",
        "gefiDVOKSFdeQsF5f1mhmzm2QnSeInKDbfaxSe0HduK+pMvzhG3fvoOuxCGlzafBW/UpLn5julOzKUsYZn9Z2mzACLMP4SvGzeOl",
        "ajBXimzQvhUyW0/pgyP8JlRU5wxMVKL6TReIqUJy7ujlXmNo0rFLVldpUt1zAeTL7AedfQmf6Hsgk87fZ3PY5R/yvbG7+cFQfBy3",
        "+OjE++6ZqiSU2S/mdbAq8SH6mdGUMqeQQXSpyUffotppyqX7Jl8Hy2dgmOoQ4+lgdJXyvq2/gBMtTRlY44nzO5eFQuUrgHdgb3To",
        "L0YT3G0SFBb+zeYioUwtydSn3MBCIigTVDb9bXXEHkpXagkKeQqFSfwCsy8hl3te9DgAAAAASUVORK5CYII=",
    ),
    "icon_title": (
        "iVBORw0KGgoAAAANSUhEUgAAABUAAAAVCAYAAACpF6WWAAAAyUlEQVR42mNU1e1koDZgQRe4dansPzEaGRkZGf7//8+gptfFiC7H",
        "RKmrsDmCBZcr8IH///F7hgmXJnyYkGuZqBU5yAYzUTPWYQbTJExZcGly8DyLInZguzFRlqvqdkIMlZJ2hluNbhiprlXT6yIcpthc",
        "SAgwEauRkZERL8YbpjAL0IOBUORguNTB8yxZ3iQpR2ELErK9f2C7MdzbB7YboxhMsvfxJSVikxhOlyIbgG4YKbmMhfj0+Z80lz57",
        "upeR1JIfb5qmRR0FAFlMaQnpYTAAAAAAAElFTkSuQmCC",
    ),
    "icon_big": (
        "iVBORw0KGgoAAAANSUhEUgAAACwAAAAxCAYAAAChzEtEAAABRklEQVR42u2azQ2DMAxGceSNOgAcYeJeOwDM5J4i0TTFCSTxRwGJ",
        "Q2kKT88/WFASEelOtLG2gIiqQ+Q4cwjWcqQ4lFCnQnOt0O2BIyL1Gg6tqDTT5sAxo1vQXLtIUtJJRL7O+Ss9YFIi1TRUDqdAc6kT",
        "l4TeSg+4LqGZhgTeiiJbg+V2nCZtrWTOw6ZEUcMtx0n4ttbU8DAtH59fzwcOcAgHZ7gfZzNIFXgN1o9zsx6bUh9sGd67D+duviv4",
        "iNVof6cz7ErbhQPWwGoXsAthtoD8d+G6VnaL53Bod5iWjoiy9l3AMWOpx5oaTsm/YVpMbzTuaNVr60Qka88GjtmLQVlZdkeKCu7W",
        "bN1zkw3HQFAmOq5tr/QjgesOP3/zXKL0TFxlgIczbDFDqMAeal3lCG95SXvXbA0cXp/3/vhua5ftw2h/p3gD5Za00hMcXe4AAAAA",
        "SUVORK5CYII=",
    ),
    "icon_open": (
        "iVBORw0KGgoAAAANSUhEUgAAABwAAAAcCAYAAAByDd+UAAAAuklEQVR42mP8////fwY6AiYGOgMWcjU6eJ5F4R/YbkyZhegGUt2H",
        "tLKAakGKDhgZGfHKw9Im1SzEl9iRHTN0UilWnyx+ienzWHHKLYRlAfSEhm74oMj4TOguJ5SBic3gZMchruDDlm8pjkNk3xzYbkyw",
        "cKAoDrEFHaXBidNCZIMdPM9StdhjIqfApsQBLNgMwxZ0xFhCdqIh1weDP+OPFt7UiEO61fgYFpKbFYip8ckqS6mVdRiHfcsbAI58",
        "T8eJNodHAAAAAElFTkSuQmCC",
    ),
}

# ── Tipos de archivo con diseno ──────────────────────────────
# Por ahora solo Word tiene su ventana "Propiedades" disenada. Los demas tipos se pueden elegir,
# pero muestran una ventana con datos de relleno (placeholder). Para disenar otro tipo, copia
# el bloque de Word, cambia "key", "title", "exts" y los textos.
FILE_TYPES = [
    {"key": "word", "title": "WORD",
     "exts": (".doc", ".docx", ".docm", ".dot", ".dotx", ".dotm"),
     "type_label": "Documento de Word ({ext})",
     "opens_with": "Word 2016",
     "phrase": "A TRABAJAR! Y TU QUE ME MIRAS EH!?",
     "personality": "Perfeccionista y continuo, siempre organizado!"},
]


def file_type_info(path):
    ext = os.path.splitext(path)[1].lower()
    for t in FILE_TYPES:
        if ext in t["exts"]:
            info = dict(t)
            info.update(ext=ext, designed=True, type_label=t["type_label"].format(ext=ext))
            return info
    short = ext[1:].upper() if len(ext) > 1 else "ARCHIVO"
    return {"key": "generic", "title": short, "ext": ext, "designed": False,
            "type_label": f"Archivo {short} ({ext or 'sin extension'})",
            "opens_with": None, "phrase": None,
            "personality": "Placeholder: sin diseno todavia"}


def _safe_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 1


# ── Moveset por defecto de cada tipo de archivo ──────────────
# (en la pantalla de seleccion se puede cambiar a mano con la tecla C)
MOVESET_BY_EXT = {
    # PowerPoint
    "gamer64": (".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".ppsm", ".pot", ".potx", ".potm"),
    # copias de seguridad
    "kris":    (".bak", ".bk", ".bkp", ".bkf", ".backup", ".bck", ".back", ".old", ".orig", ".wbk", ".xlk",
                ".sbk", ".gho", ".tib", ".abk"),
    # archivos que comprimen
    "kirby":   (".zip", ".zipx", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".tbz", ".tbz2", ".xz", ".txz",
                ".zst", ".lz", ".lzma", ".cab", ".arj", ".lzh", ".z", ".zz"),
}
DEFAULT_MOVESET = "none"        # los demas tipos (Word incluido) por ahora: el basico, sin habilidades


def default_moveset(path):
    name = os.path.basename(path).lower()
    if name.endswith("~"):                       # copia de seguridad de editores (documento.docx~)
        return "kris"
    ext = os.path.splitext(name)[1]
    for moveset, exts in MOVESET_BY_EXT.items():
        if ext in exts:
            return moveset
    return DEFAULT_MOVESET


def _moveset_index(path):
    return CHARACTERS.index(default_moveset(path))



class UIView:
    """Lleva el dibujo (792 x 441) a la ventana: escala uniforme y centrado (barras negras si sobra)."""
    def __init__(self, w=None, h=None):
        w, h = w or WIN_W, h or WIN_H
        self.s = w / DESIGN_W
        if DESIGN_H * self.s > h:
            self.s = h / DESIGN_H
        self.sw, self.sh = int(round(DESIGN_W * self.s)), int(round(DESIGN_H * self.s))
        self.ox, self.oy = (w - self.sw) // 2, (h - self.sh) // 2

    def pt(self, x, y):
        return (self.ox + int(round(x * self.s)), self.oy + int(round(y * self.s)))

    def R(self, x, y, w, h):
        x0, y0 = round(x * self.s), round(y * self.s)
        x1, y1 = round((x + w) * self.s), round((y + h) * self.s)
        return pygame.Rect(self.ox + x0, self.oy + y0, max(1, x1 - x0), max(1, y1 - y0))

    def to_design(self, pos):
        return ((pos[0] - self.ox) / self.s, (pos[1] - self.oy) / self.s)

    def font(self, size, bold=False):
        return get_font(UI_FONT, max(8, int(round(size * self.s))), bold)

    def text(self, surf, txt, x, baseline, size, color, bold=False, align="left"):
        """Texto cuya linea base (baseline) esta en la coordenada y del dibujo."""
        f = self.font(size, bold)
        img = f.render(txt, True, color)
        px, py = self.pt(x, baseline)
        py -= f.get_ascent()
        if align == "right":
            px -= img.get_width()
        elif align == "center":
            px -= img.get_width() // 2
        surf.blit(img, (px, py))
        return img.get_width() / self.s

    def width(self, txt, size, bold=False):
        return self.font(size, bold).size(txt)[0] / self.s


_UI2 = {}


def _ui2_assets(V):
    key = (V.sw, V.sh)
    if _UI2.get("key") == key:
        return _UI2
    resample = getattr(PILImage, "LANCZOS", None) or PILImage.Resampling.LANCZOS

    def load(name):
        return PILImage.open(io.BytesIO(base64.b64decode("".join(UI2_IMAGES[name])))).convert("RGBA")

    def surf_scaled(name, opaque):
        im = load(name)
        im = im.resize((max(1, int(round(im.width * V.s))), max(1, int(round(im.height * V.s)))), resample)
        sf = pygame.image.fromstring(im.tobytes(), im.size, "RGBA")
        return sf.convert() if opaque else sf.convert_alpha()

    def frame(name):
        im = load(name).convert("RGB").resize((V.sw, V.sh), resample)
        return pygame.image.fromstring(im.tobytes(), im.size, "RGB").convert()

    _UI2.clear()
    _UI2.update({
        "key": key,
        "menu": {None: frame("menu_default"), "fight": frame("menu_fight"), "online": frame("menu_online")},
        "choice_bg": frame("choice_bg"), "word_bg": frame("word_bg"),
        "spr_bottom": surf_scaled("spr_bottom", False), "icon_title": surf_scaled("icon_title", False),
        "icon_big": surf_scaled("icon_big", True), "icon_open": surf_scaled("icon_open", True),
    })
    return _UI2


# ── Menu principal ───────────────────────────────────────────
MENU_BTNS   = {"fight": (0, 39, 390, 217), "online": (354, 266, 338, 128)}   # x, y, ancho, alto (en el dibujo)
MENU_CIRCLE = (402.5, 208.5, 107)


def _menu_hover(V, pos, cur):
    x, y = V.to_design(pos)
    cx, cy, r = MENU_CIRCLE
    if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
        return cur                                   # el circulo no cambia la seleccion
    for name, (rx, ry, rw, rh) in MENU_BTNS.items():
        if rx <= x < rx + rw and ry <= y < ry + rh:
            return name
    return None


def main_menu(screen, clock):
    """Menu principal. Por ahora solo se pueden elegir 'fight' y 'online'. Devuelve esos nombres o None (salir)."""
    V = UIView()
    A = _ui2_assets(V)
    AUDIO_MGR.play_music("music_menu")
    sel = None
    while True:
        screen.fill((0, 0, 0))
        screen.blit(A["menu"][sel], (V.ox, V.oy))
        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return None
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
                old = sel
                if sel is None:
                    sel = "fight"
                elif sel == "fight" and ev.key in (pygame.K_RIGHT, pygame.K_DOWN):
                    sel = "online"
                elif sel == "online" and ev.key in (pygame.K_LEFT, pygame.K_UP):
                    sel = "fight"
                if sel != old:
                    AUDIO_MGR.play("menu_move")
            elif ev.type == pygame.MOUSEMOTION:
                new = _menu_hover(V, ev.pos, sel)
                if new != sel:
                    sel = new
                    if sel:
                        AUDIO_MGR.play("menu_move")
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                hit = _menu_hover(V, ev.pos, sel)
                if hit:
                    AUDIO_MGR.play("menu_ok")
                    return hit
            elif is_confirm(ev):
                if sel is None:
                    sel = "fight"
                else:
                    AUDIO_MGR.play("menu_ok")
                    return sel
            elif is_back(ev):
                if confirm_modal(screen, clock, ["¿Salir del juego?"], C_ORANGE,
                                 f"{key_label('confirm')}: salir", f"{key_label('back')}: quedarme"):
                    return None


# ── Pantalla "Solo Battle": elegir archivo ───────────────────
BTN_RECT   = (282, 184, 232, 57)        # boton "ELIGE UN ARCHIVO"
DD_ROW_H   = 22
DD_VIS     = 7
TAB_RECTS  = [("General", 284, 50), ("Detalles", 337, 52), ("Tutorial", 392, 51)]


def _draw_choose_button(screen, V, open_):
    x, y, w, h = BTN_RECT
    pygame.draw.rect(screen, C_DKGRAY, V.R(x, y, w, h))
    pygame.draw.rect(screen, C_UIGRAY, V.R(x + 5, y + 5, w - 10, h - 10))
    V.text(screen, "ELIGE UN ARCHIVO", 304, 217, 16, (0, 0, 0), True)
    pts = [(469, 203), (497, 203), (489, 223), (479, 223)]
    pygame.draw.polygon(screen, C_DKGRAY, [V.pt(px, py) for px, py in pts])


def _dd_rects(n_visible):
    x, y, w, h = BTN_RECT
    return [(x, y + h + i * DD_ROW_H, w, DD_ROW_H) for i in range(n_visible)]


def _draw_dropdown(screen, V, files, sel, scroll):
    vis = files[scroll:scroll + DD_VIS]
    x, y, w, h = BTN_RECT
    pygame.draw.rect(screen, C_DKGRAY, V.R(x, y + h - 3, w, 6 + len(vis) * DD_ROW_H))
    pygame.draw.rect(screen, C_UIGRAY, V.R(x + 3, y + h + 1, w - 6, len(vis) * DD_ROW_H - 1))
    f = V.font(12)
    for i, p in enumerate(vis):
        rx, ry, rw, rh = _dd_rects(len(vis))[i]
        if scroll + i == sel:
            pygame.draw.rect(screen, (255, 201, 14), V.R(rx + 3, ry, rw - 6, rh))
        name = os.path.basename(p)
        while len(name) > 3 and f.size(name)[0] / V.s > rw - 22:
            name = name[:-4] + "..."
        V.text(screen, name, rx + 10, ry + 15, 12, (0, 0, 0))
    if len(files) > DD_VIS:
        V.text(screen, f"{sel + 1}/{len(files)}", x + w - 8, y + h + len(vis) * DD_ROW_H + 14, 11, (200, 200, 200), align="right")


def _draw_props(screen, V, A, info, path, size, tab, moveset):
    """Ventana 'Propiedades' copiada de tu dibujo."""
    BLACK, WHITE = (0, 0, 0), (255, 255, 255)
    pygame.draw.rect(screen, C_NAVY, V.R(271, 64, 272, 311))
    # barra de titulo
    if info["designed"]:
        screen.blit(A["icon_title"], V.pt(275, 67))
    else:
        pygame.draw.rect(screen, WHITE, V.R(278, 69, 12, 16))
        pygame.draw.rect(screen, C_DKGRAY, V.R(278, 76, 7, 9))
    V.text(screen, f"Propiedades: {info['title'][:22]}", 304, 83, 12, WHITE, True)
    th = max(2, int(round(3 * V.s)))
    pygame.draw.line(screen, WHITE, V.pt(514, 71), V.pt(525, 84), th)
    pygame.draw.line(screen, WHITE, V.pt(525, 71), V.pt(514, 84), th)
    # cuerpo gris + pestañas + contenido blanco
    pygame.draw.rect(screen, C_UIGRAY, V.R(276, 92, 262, 278))
    for i, (name, tx, tw) in enumerate(TAB_RECTS):
        pygame.draw.rect(screen, WHITE, V.R(tx, 98, tw, 21 if i == tab else 16))
        V.text(screen, name, tx + 3, 111, 12, BLACK, True)
    pygame.draw.rect(screen, WHITE, V.R(284, 118, 246, 229))

    if tab == 0:
        _tab_general(screen, V, A, info, path, size)
    elif tab == 1:
        _tab_details(screen, V, info, path, size)
    else:
        _tab_tutorial(screen, V, moveset, default_moveset(path))


def _wrap_ui(V, text, size, width, bold=False):
    f, lines, cur = V.font(size, bold), [], ""
    for w in text.split():
        test = (cur + " " + w).strip()
        if f.size(test)[0] / V.s <= width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _tab_general(screen, V, A, info, path, size):
    BLACK, WHITE = (0, 0, 0), (255, 255, 255)
    screen.blit(A["icon_big"], V.pt(295, 133))
    if not info["designed"]:                       # insignia de relleno donde iria la W
        pygame.draw.rect(screen, C_DKGRAY, V.R(296, 151, 23, 26))
        V.text(screen, "?", 307.5, 171, 18, WHITE, True, "center")
    pygame.draw.rect(screen, BLACK, V.R(362, 148, 152, 33))
    pygame.draw.rect(screen, WHITE, V.R(365, 151, 146, 27))
    name = os.path.basename(path)
    while len(name) > 4 and V.width(name, 12, True) > 136:
        name = name[:-4] + "..."
    V.text(screen, name, 370, 168, 12, BLACK, True)

    V.text(screen, f"Tipo de archivo: {info['type_label']}", 293, 201, 11, BLACK)
    V.text(screen, "Se abre con:", 293, 229, 11, BLACK)
    if info["opens_with"]:
        screen.blit(A["icon_open"], V.pt(359, 211))
        V.text(screen, info["opens_with"], 391, 229, 11, BLACK)
    else:
        V.text(screen, "(sin definir)", 362, 229, 11, C_DKGRAY)
    V.text(screen, f"Tamaño: {size_str(size)}", 293, 257, 11, BLACK)

    phrase = f'Frase: "{info["phrase"]}"' if info["phrase"] else "Frase: (pendiente)"
    for i, ln in enumerate(_wrap_ui(V, phrase, 11, 232)[:2]):
        V.text(screen, ln, 295, 285 + i * 14, 11, BLACK)
    for i, ln in enumerate(_wrap_ui(V, info["personality"], 11, 236)[:2]):
        V.text(screen, ln, 294, 337 + i * 13, 11, BLACK)


def _tab_details(screen, V, info, path, size):
    BLACK = (0, 0, 0)
    prof = file_profile(size)
    V.text(screen, "Segun el peso del archivo:", 293, 140, 11, BLACK, True)
    rows = [("Velocidad", prof["speed"], 0.75, 1.30, C_CYAN), ("Peso", prof["weight"], 0.70, 1.50, (230, 170, 0)),
            ("Daño", prof["dmg"], 0.75, 1.35, C_RED), ("Ataque", prof["atk"], 0.70, 1.35, (30, 160, 60))]
    for i, (lbl, val, lo, hi, col) in enumerate(rows):
        y = 168 + i * 26
        V.text(screen, f"{lbl} x{val:.2f}", 293, y, 11, BLACK)
        pygame.draw.rect(screen, (210, 210, 210), V.R(385, y - 9, 130, 11))
        frac = max(0.0, min(1.0, (val - lo) / (hi - lo)))
        pygame.draw.rect(screen, col, V.R(385, y - 9, max(2, int(130 * frac)), 11))
    V.text(screen, f"Tamaño: {size_str(size)}  ({size:,} bytes)".replace(",", "."), 293, 285, 11, BLACK)
    V.text(screen, "Mas pesado = mas lento y pega mas fuerte.", 293, 311, 11, C_DKGRAY)
    V.text(screen, "Mas liviano = mas rapido, pero facil de lanzar.", 293, 325, 11, C_DKGRAY)


def _tab_tutorial(screen, V, moveset, default):
    BLACK = (0, 0, 0)
    V.text(screen, f"Moveset: {moveset.upper()}", 293, 140, 11, BLACK, True)
    note = (f"Es el moveset por defecto de este tipo de archivo. Tecla C para cambiarlo."
            if moveset == default else
            f"Cambiado a mano (el de este tipo es {default.upper()}). Tecla C para cambiarlo.")
    y = 154
    for ln in _wrap_ui(V, note, 11, 232):
        V.text(screen, ln, 293, y, 11, C_DKGRAY)
        y += 13
    y += 8
    for line in HAB_INFO[moveset]:
        for ln in _wrap_ui(V, line, 11, 232):
            if y > 340:
                return
            V.text(screen, ln, 293, y, 11, BLACK)
            y += 13
        y += 3


def choose_file_screen(screen, clock, files, label):
    """Pantalla de seleccion (como tus imagenes CHOICE y WORD).
    Devuelve (ruta_del_archivo, moveset_provisional) o None si vuelves atras."""
    if not files:
        return None
    V = UIView()
    A = _ui2_assets(V)
    AUDIO_MGR.play_music("music_menu")
    sizes = {p: _safe_size(p) for p in files}
    idx, tab, dd_open, dd_sel, dd_scroll = None, 0, False, 0, 0
    mov = 0
    BLACK, WHITE = (0, 0, 0), (255, 255, 255)

    def clamp_scroll():
        nonlocal dd_scroll
        if dd_sel < dd_scroll:
            dd_scroll = dd_sel
        elif dd_sel >= dd_scroll + DD_VIS:
            dd_scroll = dd_sel - DD_VIS + 1

    while True:
        screen.fill((0, 0, 0))
        screen.blit(A["choice_bg"] if idx is None else A["word_bg"], (V.ox, V.oy))
        V.text(screen, label, 170, 33, 16, BLACK, True)

        if idx is None:
            _draw_choose_button(screen, V, dd_open)
            if dd_open:
                _draw_dropdown(screen, V, files, dd_sel, dd_scroll)
            left = (f"{key_label('confirm')}: elegir archivo     {key_label('back')}: volver" if not dd_open
                    else f"↑ ↓: moverte     {key_label('confirm')}: elegir     {key_label('back')}: cerrar")
            right = ""
        else:
            path = files[idx]
            info = file_type_info(path)
            _draw_props(screen, V, A, info, path, sizes[path], tab, CHARACTERS[mov])
            if info["designed"]:
                screen.blit(A["spr_bottom"], V.pt(349, 406))
            else:
                pygame.draw.rect(screen, C_DKGRAY, V.R(386, 410, 28, 27))
                V.text(screen, "?", 400, 431, 18, WHITE, True, "center")
            left = f"{key_label('confirm')}: continuar     {key_label('back')}: volver"
            right = f"↑ ↓ otro archivo   ← → pestañas   C: moveset ({CHARACTERS[mov].upper()})"
        V.text(screen, left, 14, 429, 12, WHITE, True)
        if right:
            V.text(screen, right, 780, 429, 11, WHITE, True, "right")
        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()

            if ev.type == pygame.MOUSEMOTION and dd_open:
                x, y = V.to_design(ev.pos)
                for i, (rx, ry, rw, rh) in enumerate(_dd_rects(min(DD_VIS, len(files) - dd_scroll))):
                    if rx <= x < rx + rw and ry <= y < ry + rh:
                        dd_sel = dd_scroll + i

            elif ev.type == pygame.MOUSEWHEEL and dd_open:
                dd_sel = max(0, min(len(files) - 1, dd_sel - ev.y))
                clamp_scroll()

            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                x, y = V.to_design(ev.pos)
                if idx is None:
                    bx, by, bw, bh = BTN_RECT
                    if dd_open:
                        picked = None
                        for i, (rx, ry, rw, rh) in enumerate(_dd_rects(min(DD_VIS, len(files) - dd_scroll))):
                            if rx <= x < rx + rw and ry <= y < ry + rh:
                                picked = dd_scroll + i
                        if picked is not None:
                            idx, dd_open, tab = picked, False, 0
                            mov = _moveset_index(files[idx])
                            AUDIO_MGR.play("menu_ok")
                        elif not (bx <= x < bx + bw and by <= y < by + bh):
                            dd_open = False
                        else:
                            dd_open = False
                    elif bx <= x < bx + bw and by <= y < by + bh:
                        dd_open, dd_sel = True, 0
                        clamp_scroll()
                        AUDIO_MGR.play("menu_move")
                else:
                    for i, (_n, tx, tw) in enumerate(TAB_RECTS):
                        if tx <= x < tx + tw and 98 <= y < 119:
                            tab = i
                    if 505 <= x < 532 and 66 <= y < 90:            # la X de la ventana
                        idx = None
                    elif y >= 401:                                  # barra roja de abajo = continuar
                        AUDIO_MGR.play("menu_ok")
                        return files[idx], CHARACTERS[mov]

            elif ev.type == pygame.KEYDOWN:
                if idx is None and not dd_open:
                    if is_confirm(ev):
                        dd_open, dd_sel = True, 0
                        clamp_scroll()
                    elif is_back(ev):
                        return None
                elif dd_open:
                    if ev.key == pygame.K_DOWN:
                        dd_sel = (dd_sel + 1) % len(files); clamp_scroll(); AUDIO_MGR.play("menu_move")
                    elif ev.key == pygame.K_UP:
                        dd_sel = (dd_sel - 1) % len(files); clamp_scroll(); AUDIO_MGR.play("menu_move")
                    elif is_confirm(ev):
                        idx, dd_open, tab = dd_sel, False, 0
                        mov = _moveset_index(files[idx])
                        AUDIO_MGR.play("menu_ok")
                    elif is_back(ev):
                        dd_open = False
                else:
                    if ev.key == pygame.K_RIGHT:
                        tab = (tab + 1) % 3
                    elif ev.key == pygame.K_LEFT:
                        tab = (tab - 1) % 3
                    elif ev.key == pygame.K_DOWN:
                        idx = (idx + 1) % len(files); mov = _moveset_index(files[idx]); AUDIO_MGR.play("menu_move")
                    elif ev.key == pygame.K_UP:
                        idx = (idx - 1) % len(files); mov = _moveset_index(files[idx]); AUDIO_MGR.play("menu_move")
                    elif ev.key == pygame.K_c:
                        mov = (mov + 1) % len(CHARACTERS)
                    elif is_confirm(ev):
                        AUDIO_MGR.play("menu_ok")
                        return files[idx], CHARACTERS[mov]
                    elif is_back(ev):
                        dd_sel = idx
                        clamp_scroll()
                        idx = None


def info_screen(screen, clock, title, lines, color=C_YELLOW):
    font_t = get_font("segoeui", 40, True)
    font_s = get_font("segoeui", 18)
    while True:
        screen.fill(C_BG)
        t = font_t.render(title, True, color)
        screen.blit(t, t.get_rect(center=(WIN_W // 2, 130)))
        for i, ln in enumerate(lines):
            lbl = font_s.render(ln, True, C_WHITE)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W // 2, 230 + i * 30)))
        hint = font_s.render(f"{key_label('back')}: volver", True, C_GRAY)
        screen.blit(hint, hint.get_rect(center=(WIN_W // 2, WIN_H - 40)))
        pygame.display.flip()
        clock.tick(FPS)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if is_back(ev) or is_confirm(ev):
                return


def characters_screen(screen, clock):
    font_t = get_font("segoeui", 40, True)
    font_n = get_font("segoeui", 34, True)
    font_s = get_font("consolas", 15)
    font_h = get_font("segoeui", 16)
    idx = 0
    while True:
        name = CHARACTERS[idx]
        screen.fill(C_BG)
        t = font_t.render("CHARACTERS", True, C_YELLOW)
        screen.blit(t, t.get_rect(center=(WIN_W // 2, 60)))
        n = font_n.render(f"<   {name.upper()}   >", True, C_PINK)
        screen.blit(n, n.get_rect(center=(WIN_W // 2, 170)))
        spr = pygame.transform.scale(_placeholder(name + ".png", SPRITE_SIZE), (112, 112))
        screen.blit(spr, spr.get_rect(center=(WIN_W // 2, 280)))
        for i, ln in enumerate(HAB_INFO[name]):
            lbl = font_s.render(ln, True, C_WHITE)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W // 2, 380 + i * 26)))
        hint = font_h.render(f"← →: cambiar personaje        {key_label('back')}: volver", True, C_GRAY)
        screen.blit(hint, hint.get_rect(center=(WIN_W // 2, WIN_H - 36)))
        pygame.display.flip()
        clock.tick(FPS)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if is_back(ev):
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RIGHT:
                    idx = (idx + 1) % len(CHARACTERS)
                if ev.key == pygame.K_LEFT:
                    idx = (idx - 1) % len(CHARACTERS)


# ═══════════════════════ OPENING EN VIDEO ═══════════════════════

def find_opening():
    """Busca VIDEO/opening.mp4 (o opening/intro con .mp4 .mov .avi .mkv .webm) junto al juego."""
    for d in (os.path.join(BASE_DIR, "VIDEO"), BASE_DIR):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            stem, ext = os.path.splitext(n)
            if stem.lower() in ("opening", "intro") and ext.lower() in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"):
                return os.path.join(d, n)
    return None


def play_opening(screen, clock):
    """Reproduce el video de opening al abrir el juego. Se salta con la tecla de 'volver' (X)."""
    if not OPENING_ENABLED:
        return
    path = find_opening()
    if not path:
        return
    if not HAS_FFMPEG:
        mp_message(screen, clock, "Hay un opening en la carpeta VIDEO pero falta la libreria.\n"
                                  "Instalala con:  pip install imageio-ffmpeg", 4, C_YELLOW)
        return

    wav, proc = None, None
    stop = threading.Event()
    try:
        exe   = imageio_ffmpeg.get_ffmpeg_exe()
        quiet = dict(stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))   # sin ventana negra en Windows
        AUDIO_MGR.stop_music()

        # 1) el audio se extrae a un wav temporal
        wav = os.path.join(tempfile.gettempdir(), f"filesmash_opening_{os.getpid()}.wav")
        r = subprocess.run([exe, "-y", "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", "44100", "-f", "wav", wav],
                           stdout=subprocess.DEVNULL, timeout=180, **quiet)
        has_audio = r.returncode == 0 and os.path.exists(wav) and os.path.getsize(wav) > 1000

        # 2) los frames salen como imagenes crudas a la medida de la ventana
        vf = (f"fps={OPEN_FPS},scale={WIN_W}:{WIN_H}:force_original_aspect_ratio=decrease,"
              f"pad={WIN_W}:{WIN_H}:(ow-iw)/2:(oh-ih)/2:black")
        proc = subprocess.Popen([exe, "-v", "error", "-i", path, "-an", "-vf", vf,
                                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                stdout=subprocess.PIPE, **quiet)
        q = queue.Queue(maxsize=45)
        fsize = WIN_W * WIN_H * 3

        def reader():
            try:
                while not stop.is_set():
                    data = proc.stdout.read(fsize)
                    if len(data) < fsize:
                        break
                    while not stop.is_set():
                        try:
                            q.put(data, timeout=0.2)
                            break
                        except queue.Full:
                            pass
            except Exception:
                pass
            try:
                q.put(None, timeout=1)
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()

        if has_audio:
            try:
                pygame.mixer.music.load(wav)
                pygame.mixer.music.play()
            except Exception:
                pass

        font_h = get_font("segoeui", 15)
        t0, idx, frame, done = time.time(), 0, None, False
        while not done:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if is_back(ev):
                    done = True
            target = int((time.time() - t0) * OPEN_FPS)
            while idx <= target and not done:
                try:
                    data = q.get(timeout=0.25)
                except queue.Empty:
                    break                                   # el decodificador va lento: se queda el ultimo frame
                if data is None:
                    done = True
                    break
                frame = pygame.image.frombuffer(data, (WIN_W, WIN_H), "RGB")
                idx += 1
            screen.fill((0, 0, 0))
            if frame is not None:
                screen.blit(frame, (0, 0))
            hint = font_h.render(f"{key_label('back')}: saltar", True, (210, 210, 210))
            screen.blit(hint, (WIN_W - hint.get_width() - 14, WIN_H - 28))
            pygame.display.flip()
            clock.tick(60)
    except SystemExit:
        raise
    except Exception:
        import traceback
        try:
            with open(os.path.join(BASE_DIR, "opening_error.log"), "w", encoding="utf-8") as fh:
                fh.write(traceback.format_exc())
        except Exception:
            pass
    finally:
        stop.set()
        try:
            if proc is not None:
                proc.kill()
        except Exception:
            pass
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass
        try:
            if wav and os.path.exists(wav):
                os.remove(wav)
        except Exception:
            pass


# ═══════════════════════ MENU ═══════════════════════

def menu(screen, clock, archivos):
    AUDIO_MGR.play_music("music_menu")
    font_t  = pygame.font.SysFont("segoeui", 30, bold=True)
    font_b  = pygame.font.SysFont("segoeui", 16, bold=True)
    font_s  = pygame.font.SysFont("segoeui", 13)
    font_xs = pygame.font.SysFont("consolas", 11)

    selected    = None
    scroll      = 0
    MAX_VISIBLE = 12
    btn_start   = pygame.Rect(WIN_W//2-110, WIN_H-70, 220, 44)

    # Asignar personajes (todos kirby por ahora, en el futuro aleatorio)
    char_assign = {p: random.choice(CHARACTERS) for p in archivos}

    running = True
    while running:
        screen.fill(C_BG)
        t = font_t.render("FILE SMASH  -  VS CPU", True, C_YELLOW)
        screen.blit(t, (WIN_W//2-t.get_width()//2, 18))
        sub = font_b.render(
            f"{len(archivos)} archivos  |  Grupos de {MAX_POR_RONDA}  |  Personajes: "
            + " / ".join(c.upper() for c in CHARACTERS),
            True, C_GRAY)
        screen.blit(sub, (WIN_W//2-sub.get_width()//2, 56))

        ctrl = font_xs.render(
            "Controles: ← → moverse  |  ↑ saltar (x7 Kirby)  |  Z atacar  |  X habilidad especial  |  C cambiar personaje",
            True, C_CYAN)
        screen.blit(ctrl, (WIN_W//2-ctrl.get_width()//2, 80))

        if selected is not None:
            hab_info = HAB_INFO.get(char_assign[archivos[selected]], HAB_INFO["_ninguno"])
        else:
            hab_info = HAB_INFO["_ninguno"]
        for i, h in enumerate(hab_info):
            hl = font_xs.render(h, True, C_PINK)
            screen.blit(hl, (WIN_W//2-hl.get_width()//2, 100+i*14))

        list_y = 178
        visible = archivos[scroll:scroll+MAX_VISIBLE]
        for i, path in enumerate(visible):
            idx    = scroll + i
            name   = os.path.basename(path)
            char   = char_assign[path]
            is_sel = (idx == selected)
            row_r  = pygame.Rect(60, list_y+i*28, WIN_W-120, 26)
            bg = (40,60,90) if is_sel else ((25,25,40) if i%2==0 else (20,20,35))
            pygame.draw.rect(screen, bg, row_r, border_radius=4)
            if is_sel:
                pygame.draw.rect(screen, C_YELLOW, row_r, 2, border_radius=4)

            col = make_color_for(name)
            pygame.draw.rect(screen, col, (row_r.x+4, row_r.y+6, 14, 14), border_radius=3)
            nlbl = font_s.render(name[:55], True, C_WHITE)
            screen.blit(nlbl, (row_r.x+24, row_r.y+6))
            clbl = font_xs.render(f"[{char.upper()}]", True, C_PINK)
            screen.blit(clbl, (row_r.x+row_r.w-clbl.get_width()-8, row_r.y+8))

        if len(archivos) > MAX_VISIBLE:
            sh = font_xs.render(
                f"↑↓ scroll ({scroll+1}-{min(scroll+MAX_VISIBLE, len(archivos))} de {len(archivos)})",
                True, C_GRAY)
            screen.blit(sh, (WIN_W//2-sh.get_width()//2, list_y+MAX_VISIBLE*28+4))

        if selected is not None:
            _sp = archivos[selected]
            try:
                _sz = os.path.getsize(_sp)
            except OSError:
                _sz = 1
            _pr = file_profile(_sz)
            _l1 = font_xs.render(f"{os.path.basename(_sp)[:34]}  ({size_str(_sz)})", True, C_WHITE)
            _l2 = font_xs.render(f"Vel x{_pr['speed']:.2f}  Peso x{_pr['weight']:.2f}  Daño x{_pr['dmg']:.2f}  Atq x{_pr['atk']:.2f}",
                                 True, C_CYAN)
            screen.blit(_l1, (60, WIN_H - 66))
            screen.blit(_l2, (60, WIN_H - 50))

        pygame.draw.rect(screen, C_ORANGE, btn_start, border_radius=8)
        pygame.draw.rect(screen, C_YELLOW, btn_start, 2, border_radius=8)
        btn_txt = ">  INICIAR" + (
            f"  ({os.path.basename(archivos[selected])[:20]})"
            if selected is not None else "  (todo IA)")
        btl = font_b.render(btn_txt, True, C_DARK)
        screen.blit(btl, btl.get_rect(center=btn_start.center))

        enter_lbl = font_xs.render(f"o presiona {key_label('confirm')} para iniciar      {key_label('back')}: volver", True, C_GRAY)
        screen.blit(enter_lbl, enter_lbl.get_rect(center=(WIN_W//2, WIN_H-8)))

        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if is_confirm(ev):
                    AUDIO_MGR.stop_music()
                    return selected, char_assign
                if is_back(ev):
                    return None
                if ev.key == pygame.K_c and selected is not None:
                    cur = char_assign[archivos[selected]]
                    char_assign[archivos[selected]] = CHARACTERS[(CHARACTERS.index(cur) + 1) % len(CHARACTERS)]
                if ev.key == pygame.K_DOWN:
                    scroll = min(scroll+1, max(0, len(archivos)-MAX_VISIBLE))
                if ev.key == pygame.K_UP:
                    scroll = max(scroll-1, 0)
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if btn_start.collidepoint(ev.pos):
                    AUDIO_MGR.stop_music()
                    return selected, char_assign
                for i in range(min(MAX_VISIBLE, len(archivos)-scroll)):
                    row_r = pygame.Rect(60, list_y+i*28, WIN_W-120, 26)
                    if row_r.collidepoint(ev.pos):
                        idx = scroll+i
                        selected = idx if selected != idx else None
            if ev.type == pygame.MOUSEWHEEL:
                scroll = max(0, min(scroll-ev.y, max(0, len(archivos)-MAX_VISIBLE)))


# ═══════════════════════ RONDA ═══════════════════════

def run_round(screen, clock, archivos_ronda, player_path,
              char_assign, round_num, total_rounds):
    AUDIO_MGR.play_music("music_battle")
    platforms = make_platforms(len(archivos_ronda))
    colors    = {p: make_color_for(os.path.basename(p)) for p in archivos_ronda}
    sprites   = {p: load_sprite(p) for p in archivos_ronda}

    main_plat = platforms[0]
    spacing   = main_plat.w // (len(archivos_ronda)+1)
    fighters  = []
    for i, path in enumerate(archivos_ronda):
        x    = main_plat.x + spacing*(i+1) - SPRITE_SIZE//2
        y    = main_plat.top - SPRITE_SIZE - 2
        char = char_assign.get(path, "kirby")
        is_p = (path == player_path)
        fighters.append(Fighter(path, x, y, sprites[path], colors[path],
                                character=char, is_player=is_p))

    font_big = pygame.font.SysFont("segoeui", 48, bold=True)
    font_med = pygame.font.SysFont("segoeui", 20, bold=True)

    for n in ["3", "2", "1", "¡PELEA!"]:
        for _ in range(FPS if n != "¡PELEA!" else FPS//2):
            screen.fill(C_BG)
            draw_stage(screen, platforms)
            for f in fighters: f.draw(screen)
            lbl = font_big.render(n, True, C_YELLOW)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W//2, WIN_H//2)))
            pygame.display.flip()
            clock.tick(FPS)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT: pygame.quit(); sys.exit()

    prev_special = False
    rframe = 0

    while True:
        keys = pygame.key.get_pressed()
        cur_special = keys[K_SPECIAL]
        special_pressed  = cur_special and not prev_special
        special_released = not cur_special and prev_special

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT: pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE: pygame.quit(); sys.exit()
                player = next((f for f in fighters if f.is_player and f.alive), None)
                if player and ev.key == K_JUMP:
                    player.request_jump()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for f in fighters:
                    if f.alive and f.rect.collidepoint(ev.pos):
                        for ff in fighters: ff.is_player = False
                        f.is_player = True

        # Update
        for f in fighters:
            if not f.alive: continue
            sp = special_pressed  if f.is_player else False
            sr = special_released if f.is_player else False
            f.update(fighters, platforms,
                     keys if f.is_player else None, sp, sr)

            # Hitbox normal Z
            f.resolve_normal_attack(fighters)

            # Hitbox martillo Kirby
            if f.kirby:
                mhb, mpow = f.kirby.get_hammer_hitbox_and_power()
                if mhb:
                    for other in fighters:
                        if other is f or not other.alive: continue
                        if mhb.colliderect(other.rect):
                            d = 1 if other.rect.centerx > f.rect.centerx else -1
                            other.receive_hit(mpow, d)
                            AUDIO_MGR.play("hit")

            # Eliminacion
            if f.is_out_of_bounds():
                f.alive = False
                AUDIO_MGR.play("ko")
                try:
                    if os.path.exists(f.path):
                        os.remove(f.path)
                        print(f"[ELIMINADO] {f.name}")
                except Exception as e:
                    print(f"[ERROR] {f.name}: {e}")

        prev_special = cur_special
        rframe += 1
        if rframe == SUDDEN_DEATH_FRAMES:
            del platforms[1:]            # muerte subita: evita rondas eternas (CPUs que no se alcanzan)

        # Dibujar
        draw_stage(screen, platforms)
        for f in fighters: f.draw(screen)
        draw_hud(screen, fighters, round_num, total_rounds)
        if SUDDEN_DEATH_FRAMES <= rframe < SUDDEN_DEATH_FRAMES + FPS * 3:
            _draw_banner(screen, "MUERTE SUBITA: solo queda el escenario principal", C_RED, 90)

        # Ganador
        alive_now = [f for f in fighters if f.alive]
        if len(alive_now) <= 1:
            winner = alive_now[0] if alive_now else None
            if winner:
                for _ in range(FPS*2):
                    draw_stage(screen, platforms)
                    winner.draw(screen)
                    draw_hud(screen, fighters, round_num, total_rounds)
                    msg = font_med.render(f"{winner.name[:40]}  GANA!", True, C_YELLOW)
                    pygame.draw.rect(screen, C_DARK,
                                     msg.get_rect(center=(WIN_W//2, WIN_H//2)).inflate(20,14),
                                     border_radius=6)
                    screen.blit(msg, msg.get_rect(center=(WIN_W//2, WIN_H//2)))
                    pygame.display.flip()
                    clock.tick(FPS)
                    for ev in pygame.event.get():
                        if ev.type == pygame.QUIT: pygame.quit(); sys.exit()
            AUDIO_MGR.stop_music()
            return winner.path if winner else None

        pygame.display.flip()
        clock.tick(FPS)


# ═══════════════════════ MAIN ═══════════════════════

def play_cpu_mode(screen, clock, archivos):
    """Torneo contra CPUs con todos los archivos de PVP. El perdedor se borra del disco."""
    pick = choose_file_screen(screen, clock, archivos, "SOLO BATTLE")
    if pick is None:
        return False                      # volvio atras
    player_path, moveset = pick
    char_assign = {p: default_moveset(p) for p in archivos}          # cada archivo usa el moveset de su tipo
    char_assign[player_path] = moveset
    AUDIO_MGR.stop_music()

    sobrevivientes = archivos[:]
    ronda = 0

    while len(sobrevivientes) > 1:
        ronda += 1
        random.shuffle(sobrevivientes)
        grupos = [sobrevivientes[i:i+MAX_POR_RONDA]
                  for i in range(0, len(sobrevivientes), MAX_POR_RONDA)]
        total_rondas = math.ceil(math.log2(max(len(sobrevivientes), 2)))
        ganadores = []

        for g_idx, grupo in enumerate(grupos):
            if len(grupo) == 1:
                ganadores.append(grupo[0]); continue
            pp = player_path if (player_path and player_path in grupo) else None
            winner = run_round(screen, clock, grupo, pp,
                               char_assign, ronda, total_rondas)
            if winner:
                ganadores.append(winner)

        sobrevivientes = [p for p in ganadores if os.path.exists(p)]

    font_big = pygame.font.SysFont("segoeui", 36, bold=True)
    font_med = pygame.font.SysFont("segoeui", 18)
    if sobrevivientes:
        campeon = os.path.basename(sobrevivientes[0])
        spr = load_sprite(sobrevivientes[0], size=120)
        done = False
        while not done:
            screen.fill(C_BG)
            screen.blit(spr, (WIN_W//2-60, WIN_H//2-110))
            lbl = font_big.render(f"CAMPEON:  {campeon[:34]}", True, C_YELLOW)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W//2, WIN_H//2+40)))
            sub = font_med.render(f"¡CAMPEÓN ABSOLUTO!  —  {key_label('back')} para salir", True, C_ORANGE)
            screen.blit(sub, sub.get_rect(center=(WIN_W//2, WIN_H//2+80)))
            pygame.display.flip(); clock.tick(FPS)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT or is_back(ev) or is_confirm(ev):
                    done = True
    return True


def set_window_icon():
    """Icono de la ventana y de la barra de tareas (el de pygame sale por defecto).
    Busca icon.ico / icon.png (da igual mayusculas) junto al juego o dentro del .exe."""
    dirs = [BASE_DIR]
    if getattr(sys, "_MEIPASS", None):
        dirs.insert(0, sys._MEIPASS)            # archivos metidos dentro del .exe con --add-data
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n.lower() in ("icon.ico", "icon.png", "icono.ico", "icono.png"):
                try:
                    im = PILImage.open(os.path.join(d, n)).convert("RGBA").resize((64, 64))
                    pygame.display.set_icon(pygame.image.fromstring(im.tobytes(), im.size, "RGBA"))
                    return
                except Exception:
                    pass


def info_window(lines, secs=25):
    """Ventana simple con un aviso. Sirve tambien en el .exe, que no tiene consola."""
    pygame.init()
    set_window_icon()
    scr  = pygame.display.set_mode((820, 130 + 26 * len(lines)))
    pygame.display.set_caption("⚔ FILE SMASH ⚔")
    clk  = pygame.time.Clock()
    font = pygame.font.SysFont("segoeui", 17)
    end  = pygame.time.get_ticks() + secs * 1000
    while pygame.time.get_ticks() < end:
        scr.fill(C_BG)
        for i, ln in enumerate(lines):
            scr.blit(font.render(ln[:105], True, C_WHITE), (24, 24 + i * 26))
        hint = font.render("Presiona cualquier tecla para cerrar", True, C_GRAY)
        scr.blit(hint, (24, 130 + 26 * len(lines) - 40))
        pygame.display.flip()
        clk.tick(30)
        for ev in pygame.event.get():
            if ev.type in (pygame.QUIT, pygame.KEYDOWN):
                pygame.quit()
                return
    pygame.quit()


def main():
    global AUDIO_MGR

    if not os.path.isdir(PVP_FOLDER):
        os.makedirs(PVP_FOLDER)
        info_window(["Se creo la carpeta PVP:", PVP_FOLDER, "",
                     "Pon ahi COPIAS de los archivos que van a pelear (el que pierde se BORRA)",
                     "y vuelve a abrir el juego."])
        return

    if len(list_pvp_files()) < 1:
        info_window(["La carpeta PVP esta vacia:", PVP_FOLDER, "",
                     "Pon al menos 1 archivo (2 o mas para jugar contra CPUs) y vuelve a abrir el juego."])
        return

    pygame.init()
    set_window_icon()                       # antes de crear la ventana
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("⚔ FILE SMASH ⚔")
    clock  = pygame.time.Clock()
    AUDIO_MGR = AudioManager()
    load_settings()
    play_opening(screen, clock)

    running = True
    while running:
        choice = main_menu(screen, clock)
        if choice is None:
            break
        if choice == "fight":                       # pelea contra bots
            files = list_pvp_files()
            if len(files) < 2:
                mp_message(screen, clock, "Necesitas 2 archivos o mas en la carpeta PVP\npara pelear contra bots.",
                           3.5, C_YELLOW)
                continue
            if play_cpu_mode(screen, clock, files):
                running = False                     # termino el torneo: se cierra como antes
        elif choice == "online":                    # pelea contra otros jugadores
            multiplayer_menu(screen, clock)
    pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        err = traceback.format_exc()
        try:
            io_path = os.path.join(BASE_DIR, "error.log")
            with open(io_path, "w", encoding="utf-8") as fh:
                fh.write(err)
        except Exception:
            pass
        try:
            info_window(["El juego tuvo un error (se guardo en error.log):", ""]
                        + err.strip().splitlines()[-5:], 40)
        except Exception:
            pass