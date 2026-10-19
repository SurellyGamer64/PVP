"""
FILE SMASH - by Claudsito
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
SERVER_URL    = "https://pvp-roq9.onrender.com"     # tu servidor de salas, ej: "wss://file-smash.onrender.com" (ver RELAYSERV.py)
LAN_PORT      = 8765   # puerto de las salas en red local
MAX_PLAYERS   = 8
NET_TICK      = 2      # el host manda el estado cada 2 frames (30 veces por segundo)
MP_STAKES     = True   # multijugador: el que pierde BORRA su archivo. Pon False para practicar sin riesgo.

# ── Menu / opening ───────────────────────────────────────────
OPENING_ENABLED = True   # si existe VIDEO/opening.mp4 se reproduce al abrir el juego (X para saltar)
OPEN_FPS      = 30
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

# ═══════════════════════ AUDIO MANAGER ═══════════════════════

class AudioManager:
    def __init__(self):
        self.sounds  = {}
        self.enabled = True
        self.sink    = None   # el host de multijugador anota aqui los sonidos para los demas
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

    def play_music(self, key, loop=True):
        path = AUDIO.get(key, "")
        if os.path.exists(path):
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(0.5)
                pygame.mixer.music.play(-1 if loop else 0)
            except Exception as e:
                print(f"[audio] No se pudo reproducir musica {key}: {e}")

    def stop_music(self):
        pygame.mixer.music.stop()

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
        "X (quieto): Absorber enemigo y copiar habilidad",
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
        self.copied_ability= None       # "rock"/"hammer"/"sword" copiado

        # Proyectiles activos de shockwave
        self.shockwaves    = []         # lista de {rect, vx, timer}

    # ─── ACTIVAR ESPECIAL (llamado al presionar X) ───────────
    def activate(self, keys):
        o = self.owner
        if o.knockback_timer > 4 or not o.alive:
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
    def _start_inhale(self):
        self.inhaling    = True
        self.inhale_timer= 40
        AUDIO_MGR.play("kirby_inhale")

    def _update_inhale(self, fighters):
        o = self.owner
        if not self.inhaling:
            return
        self.inhale_timer -= 1

        # Area de absorcion frente a Kirby
        inhale_hb = pygame.Rect(
            o.rect.centerx if o.facing==1 else o.rect.left-80,
            o.rect.top, 80, o.rect.h
        )
        for other in fighters:
            if other is o or not other.alive:
                continue
            if inhale_hb.colliderect(other.rect):
                # Absorber: copiar habilidad del oponente
                if hasattr(other, "kirby") and other.kirby:
                    # copiar su habilidad especial de X-abajo (rock), etc.
                    self.copied_ability = "rock"
                self.inhaling = False
                break

        if self.inhale_timer <= 0:
            self.inhaling = False

    # ─── UPDATE GENERAL ──────────────────────────────────────
    def update(self, fighters, platforms, keys_held, special_pressed, special_released):
        o = self.owner

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

    def is_out_of_bounds(self):
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
            keys_held = keys if keys else pygame.key.get_pressed()
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

KEYBIT = {K_LEFT: 1, K_RIGHT: 2, K_UP: 4, K_DOWN: 8, K_ATTACK: 16, K_SPECIAL: 32}
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
            self.mask = int(d.get("k", 0)) & 63
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
            "is_player", "remote", "atk_hit_ids"}
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
    return d


def apply_fighter(f, d):
    for k, v in d.items():
        if k.startswith("sp."):
            if f.special:
                setattr(f.special, k[3:], _dec(v))
        elif k not in _SKIP_F:
            setattr(f, k, _dec(v))


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
            pick = mp_pick_screen(screen, clock, files)
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
    pick = mp_pick_screen(screen, clock, files)
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


# ═══════════════════════ MENU PRINCIPAL (copia de tu dibujo) ═══════════════════════
# El arte de los 4 bloques y la imagen de la derecha salen de tu dibujo (guardados aqui dentro).
# Para cambiar el texto de la derecha edita NEWS_TITLE / NEWS_BODY.
# Para cambiar la imagen: pon un archivo  news.png  junto al juego.

NEWS_TITLE = "V.1 IS HERE!!"
NEWS_BODY = [
    "Enjoy the BETA VERSION of FILES PVP!!",
    "In this Game, you grab your files, and you make them fight until theres only one left",
    "All the files are on your hands, even if it is on pvp, OR IN STORY MODE!!",
    "Fight against the unraveled SYSTEM32! AND SAVE YOUR LAPTOP FROM DESTRUCTION!",
]

PANEL_GRAY = (195, 195, 195)

# Poligonos de cada boton, en coordenadas del dibujo original (470 x 522)
MENU_POLY = {
    "fight":      [(0, 0), (222, 0), (224, 207), (0, 226)],
    "story":      [(222, 0), (480, 0), (480, 215), (224, 207)],
    "characters": [(0, 226), (224, 207), (480, 215), (480, 396), (0, 392.5)],
    "settings":   [(0, 392.5), (480, 396), (480, 522), (0, 522)],
}

MENU_ART_B64 = (
    "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"
)

MENU_PREVIEW_B64 = (
    "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"
)

_MENU = {}


def _wrap_text(font, text, width):
    lines, cur = [], ""
    for w in text.split():
        test = (cur + " " + w).strip()
        if font.size(test)[0] <= width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _menu_assets():
    if _MENU:
        return _MENU
    from PIL import ImageDraw, ImageChops
    resample = getattr(PILImage, "LANCZOS", None) or PILImage.Resampling.LANCZOS
    s = WIN_H / 522.0                                   # el dibujo se escala al alto de la ventana

    art_img = PILImage.open(io.BytesIO(base64.b64decode(MENU_ART_B64))).convert("RGBA")
    sw, sh = int(round(art_img.width * s)), WIN_H
    art_s = art_img.resize((sw, sh), resample)
    art = pygame.image.fromstring(art_s.tobytes(), (sw, sh), "RGBA")
    alpha = art_s.getchannel("A")

    regions = {}
    white = PILImage.new("L", (sw, sh), 255)
    for name, pts in MENU_POLY.items():
        pm = PILImage.new("L", (sw, sh), 0)
        ImageDraw.Draw(pm).polygon([(x * s, y * s) for x, y in pts], fill=255)
        pm = ImageChops.multiply(pm, alpha)
        overlay = pygame.image.fromstring(PILImage.merge("RGBA", (white, white, white, pm)).tobytes(),
                                          (sw, sh), "RGBA")
        mask = pygame.mask.from_surface(overlay, 128)
        biggest = max(mask.connected_components(), key=lambda m: m.count())
        regions[name] = {"mask": mask, "overlay": overlay, "outline": biggest.outline(3)}

    # ── panel de la derecha ──
    zig_x = int(466 * s)
    cw = int(293 * s)
    px0 = zig_x + (WIN_W - zig_x - cw) // 2
    pcx = px0 + cw // 2

    pw, ph = int(266 * s), int(182 * s)
    prev_img = None
    news = os.path.join(BASE_DIR, "news.png")
    try:
        prev_img = PILImage.open(news if os.path.exists(news) else io.BytesIO(base64.b64decode(MENU_PREVIEW_B64)))
        prev_img = prev_img.convert("RGB").resize((pw, ph), resample)
    except Exception:
        prev_img = PILImage.open(io.BytesIO(base64.b64decode(MENU_PREVIEW_B64))).convert("RGB").resize((pw, ph), resample)
    preview = pygame.image.fromstring(prev_img.tobytes(), (pw, ph), "RGB")

    title_font = pygame.font.SysFont("impact,arialblack,arial", int(round(34 * s)), italic=True)
    title = title_font.render(NEWS_TITLE, True, (255, 255, 255))

    body, y_end = [], 0
    for size in range(int(round(17 * s)), 11, -1):
        font = pygame.font.SysFont("arial", size, bold=True)
        line_h = int(round(size * 1.14))
        y = int(262 * s)
        body = []
        for para in NEWS_BODY:
            for ln in _wrap_text(font, para, cw):
                body.append((font.render(ln, True, (255, 255, 255)), (px0, y)))
                y += line_h
            y += line_h                                   # linea en blanco entre parrafos
        y_end = y - line_h
        if y_end <= WIN_H - 12:
            break

    _MENU.update({
        "art": art, "regions": regions, "preview": preview,
        "preview_pos": (pcx - pw // 2, int(28 * s)),
        "title": title, "title_pos": (pcx - title.get_width() // 2, int(222 * s)),
        "body": body,
    })
    return _MENU


def _menu_hit(A, pos):
    x, y = pos
    for name, r in A["regions"].items():
        w, h = r["mask"].get_size()
        if 0 <= x < w and 0 <= y < h and r["mask"].get_at((x, y)):
            return name
    return None


def main_menu(screen, clock):
    """Menu principal. Devuelve 'fight', 'story', 'characters', 'settings' o None (salir)."""
    A = _menu_assets()
    AUDIO_MGR.play_music("music_menu")
    sel, last_top, t = "fight", "fight", 0
    font_h = get_font("segoeui", 14)
    while True:
        t += 1
        screen.fill(PANEL_GRAY)
        screen.blit(A["art"], (0, 0))
        screen.blit(A["preview"], A["preview_pos"])
        screen.blit(A["title"], A["title_pos"])
        for surf, pos in A["body"]:
            screen.blit(surf, pos)

        reg = A["regions"][sel]
        pulse = 0.5 + 0.5 * math.sin(t * 0.12)
        reg["overlay"].set_alpha(int(20 + 45 * pulse))
        screen.blit(reg["overlay"], (0, 0))
        if len(reg["outline"]) > 2:
            pygame.draw.lines(screen, (255, 255, 255), True, reg["outline"], 4)

        hint = font_h.render(f"{key_label('confirm')}: continuar     {key_label('back')}: volver", True, (80, 80, 80))
        screen.blit(hint, (WIN_W - hint.get_width() - 14, 8))
        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return None
            if ev.type == pygame.KEYDOWN:
                old = sel
                if ev.key == pygame.K_LEFT and sel == "story":
                    sel = "fight"
                elif ev.key == pygame.K_RIGHT and sel == "fight":
                    sel = "story"
                elif ev.key == pygame.K_DOWN:
                    sel = {"fight": "characters", "story": "characters", "characters": "settings"}.get(sel, sel)
                elif ev.key == pygame.K_UP:
                    sel = {"settings": "characters", "characters": last_top}.get(sel, sel)
                if sel in ("fight", "story"):
                    last_top = sel
                if sel != old:
                    AUDIO_MGR.play("menu_move")
            if ev.type == pygame.MOUSEMOTION:
                hit = _menu_hit(A, ev.pos)
                if hit and hit != sel:
                    sel = hit
                    if sel in ("fight", "story"):
                        last_top = sel
                    AUDIO_MGR.play("menu_move")
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                hit = _menu_hit(A, ev.pos)
                if hit:
                    AUDIO_MGR.play("menu_ok")
                    return hit
            if is_confirm(ev):
                AUDIO_MGR.play("menu_ok")
                return sel
            if is_back(ev):
                if confirm_modal(screen, clock, ["¿Salir del juego?"], C_ORANGE,
                                 f"{key_label('confirm')}: salir", f"{key_label('back')}: quedarme"):
                    return None


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
    res = menu(screen, clock, archivos)
    if res is None:
        return False                      # volvio atras
    player_idx, char_assign = res
    player_path = archivos[player_idx] if player_idx is not None else None

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
        if choice == "fight":
            while True:
                files = list_pvp_files()
                mode = mode_screen(screen, clock, len(files))
                if mode is None:
                    break
                if mode == "cpu":
                    if play_cpu_mode(screen, clock, files):
                        running = False             # termino el torneo: se cierra como antes
                        break
                elif mode == "mp":
                    multiplayer_menu(screen, clock)
        elif choice == "story":
            info_screen(screen, clock, "STORY MODE",
                        ["Muy pronto...", "",
                         "Pelea contra el SYSTEM32 desatado",
                         "y salva tu laptop de la destruccion!"])
        elif choice == "characters":
            characters_screen(screen, clock)
        elif choice == "settings":
            info_screen(screen, clock, "SETTINGS",
                        [f"Controles de los menus:   {key_label('confirm')} = continuar     {key_label('back')} = volver",
                         "(Enter y Esc tambien funcionan)", "",
                         "Muy pronto podras cambiarlos desde aqui."])
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