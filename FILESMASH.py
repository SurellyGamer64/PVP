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
import json, zlib, base64, threading, queue, socket, time
from functools import lru_cache
from PIL import Image as PILImage

# Multijugador: pip install websockets
try:
    from websockets.sync.client import connect as ws_connect
    HAS_WS = True
except Exception:
    HAS_WS = False

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
SERVER_URL    = ""     # tu servidor de salas, ej: "wss://file-smash.onrender.com" (ver relay_server.py)
LAN_PORT      = 8765   # puerto de las salas en red local
MAX_PLAYERS   = 8
NET_TICK      = 2      # el host manda el estado cada 2 frames (30 veces por segundo)

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
              "shockwave", "kris_save", "kris_slash", "kris_act", "gamer_phase", "gamer_missile"]
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
       Mas pesado : mas lento, mas pesado (cuesta lanzarlo) y pega mas fuerte.
       Mas liviano: mas rapido, facil de lanzar fuera del campo y pega menos."""
    size = max(1, int(size))
    t = min(1.0, max(0.0, (math.log2(size) - 10.0) / 18.0))
    return {"t": t,
            "weight": 0.7 + 0.8 * t,      # 0.70 .. 1.50
            "speed" : 1.3 - 0.55 * t,     # 1.30 .. 0.75
            "dmg"   : 0.75 + 0.6 * t}     # 0.75 .. 1.35


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
            self.combo_timer = 42
            self.attack_cd   = 50 if self.combo_step == 3 else 16
            AUDIO_MGR.play("kris_slash")
        elif self.character == "gamer64":
            self.attack_cd = 24
        else:
            self.attack_cd = ATTACK_CD

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
#   - Un servidor "relay" (relay_server.py) une al HOST con los demas jugadores.
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
    return {"name": os.path.basename(path)[:40], "char": char,
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

    # ── conectar ────────────────────────────────────────────
    def host(self, lan=False):
        self.role, self.pid, self.status = "host", 0, "connecting"
        if lan:
            try:
                if BASE_DIR not in sys.path:
                    sys.path.insert(0, BASE_DIR)
                import relay_server
            except Exception as e:
                return self._fail(f"Falta relay_server.py junto al juego (o la libreria websockets): {e}")
            _th, stop, err = relay_server.start_background(LAN_PORT)
            if err is not None:
                return self._fail(f"No se pudo abrir el puerto {LAN_PORT} (¿ya hay una sala abierta?): {err}")
            self._stop_local = stop
            self.display_code = lan_encode(get_lan_ip())
            url = f"ws://127.0.0.1:{LAN_PORT}"
        else:
            if not SERVER_URL:
                return self._fail("Falta configurar SERVER_URL al inicio de file_smash.py "
                                  "(ver relay_server.py). Mientras tanto usa la sala LAN.")
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
        return {"t": "roster", "players": [
            {"pid": pid, "name": p["name"], "char": p["char"], "size": p["size"]}
            for pid, p in sorted(self.players.items())]}

    def _broadcast_roster(self):
        self.send_all(self._roster_msg())

    def host_start(self):
        """El host arma la partida y avisa a todos. Devuelve (jugadores, plataformas)."""
        plist = [{"pid": pid, "name": p["name"], "char": p["char"], "size": p["size"], "spr": p["spr"]}
                 for pid, p in sorted(self.players.items())]
        plats = make_platforms(len(plist))
        self.send_all({"t": "start", "players": plist,
                       "plats": [[r.x, r.y, r.w, r.h] for r in plats]})
        return plist, plats

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
                AUDIO_MGR.play("ko")        # (en multijugador NO se borra ningun archivo)

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
        msg = f"🏆  {winner.name[:40]}  GANA!" if winner else "Empate"
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
    end_msg, end_frames = None, 0
    frame, last_mask, last_send = 0, -1, -99

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                sess.close()
                sess.status = "closed"
                AUDIO_MGR.stop_music()
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
            elif e[0] == "end" and end_msg is None:
                end_msg = e[1]
            elif e[0] in ("host_left", "closed"):
                AUDIO_MGR.stop_music()
                # si la pelea ya habia terminado, no es un error: el host solo cerro despues
                return "done" if end_msg is not None else "closed"

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
        if cd_text and frame - cd_frame < (45 if cd_text.startswith("¡") else 55):
            lbl = big.render(cd_text, True, C_YELLOW)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W // 2, WIN_H // 2)))
        if mine is not None and not mine.alive and end_msg is None:
            _draw_banner(screen, "ELIMINADO — mirando la pelea (ESC para salir)", C_RED, 70)
        if end_msg is not None:
            w = end_msg.get("winner", -1)
            wf = next((f for f in fighters if f.pid == w), None)
            if w == -2:
                _draw_banner(screen, "El host cancelo la partida")
            elif wf is not None:
                _draw_banner(screen, f"🏆  {wf.name[:40]}  GANA!")
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


def mode_screen(screen, clock, n_archivos):
    AUDIO_MGR.play_music("music_menu")
    font_t = get_font("segoeui", 36, True)
    font_b = get_font("segoeui", 22, True)
    font_s = get_font("segoeui", 14)
    btn_cpu = pygame.Rect(WIN_W // 2 - 260, 190, 520, 90)
    btn_mp  = pygame.Rect(WIN_W // 2 - 260, 310, 520, 90)
    cpu_ok  = n_archivos >= 2
    while True:
        screen.fill(C_BG)
        t = font_t.render("⚔  FILE SMASH  ⚔", True, C_YELLOW)
        screen.blit(t, t.get_rect(center=(WIN_W // 2, 70)))
        sub = font_s.render("Mientras mas PESADO es el archivo: mas lento y pesado, pero mas daño.  "
                            "Mientras mas LIVIANO: mas rapido, pero mas facil de lanzar.", True, C_GRAY)
        screen.blit(sub, sub.get_rect(center=(WIN_W // 2, 120)))

        for rect, txt, line2, ok, col in (
            (btn_cpu, "1   VS CPU", "Todos los archivos de PVP pelean. El perdedor se BORRA del disco."
             if cpu_ok else "Necesitas al menos 2 archivos en la carpeta PVP", cpu_ok, C_ORANGE),
            (btn_mp, "2   MULTIJUGADOR", "Hasta 8 jugadores con codigo de sala. No se borra nada.", True, C_CYAN),
        ):
            pygame.draw.rect(screen, col if ok else (60, 60, 70), rect, border_radius=10)
            pygame.draw.rect(screen, C_YELLOW if ok else C_GRAY, rect, 2, border_radius=10)
            a = font_b.render(txt, True, C_DARK)
            b = font_s.render(line2, True, C_DARK)
            screen.blit(a, a.get_rect(center=(rect.centerx, rect.y + 32)))
            screen.blit(b, b.get_rect(center=(rect.centerx, rect.y + 62)))
        hint = font_s.render("ESC para salir", True, C_GRAY)
        screen.blit(hint, hint.get_rect(center=(WIN_W // 2, WIN_H - 30)))
        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return None
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key in (pygame.K_1, pygame.K_KP1) and cpu_ok:
                    return "cpu"
                if ev.key in (pygame.K_2, pygame.K_KP2):
                    return "mp"
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if btn_cpu.collidepoint(ev.pos) and cpu_ok:
                    return "cpu"
                if btn_mp.collidepoint(ev.pos):
                    return "mp"


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
        h = font_xs.render("↑↓ archivo   ←→ personaje   ENTER continuar   ESC volver", True, C_CYAN)
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
        screen.blit(font_b.render("PERSONAJE", True, C_ORANGE), (px, 252))
        ch = font_t.render(f"◀  {CHARACTERS[ci].upper()}  ▶", True, C_PINK)
        screen.blit(ch, (px, 280))

        for i, line in enumerate(HAB_INFO[CHARACTERS[ci]]):
            hl = font_xs.render(line, True, C_PINK)
            screen.blit(hl, hl.get_rect(center=(WIN_W // 2, 440 + i * 16)))
        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
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
         else "⚠ Falta configurar SERVER_URL (ver relay_server.py)", bool(SERVER_URL), C_ORANGE),
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
        hint = font_s.render("ESC para volver", True, C_GRAY)
        screen.blit(hint, hint.get_rect(center=(WIN_W // 2, WIN_H - 30)))
        pygame.display.flip()
        clock.tick(FPS)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
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
                msg = (f"ENTER: empezar ({n}/{MAX_PLAYERS} jugadores)   ·   ESC: cerrar sala" if n >= 2
                       else "Esperando jugadores...  (necesitas al menos 2)   ·   ESC: cerrar sala")
            else:
                msg = "Esperando a que el host empiece la partida...   ·   ESC: salir"
            hl = font_s.render(msg, True, C_ORANGE)
            screen.blit(hl, hl.get_rect(center=(WIN_W // 2, WIN_H - 30)))
        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return
                if (ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and sess.role == "host"
                        and sess.status == "lobby" and len(sess.players) >= 2):
                    plist, plats = sess.host_start()
                    run_mp_host_match(screen, clock, sess, plist, plats)
                    sess.after_match()
                    AUDIO_MGR.play_music("music_menu")


def multiplayer_menu(screen, clock, archivos):
    if not HAS_WS:
        mp_message(screen, clock, "Falta la libreria de red.\nInstalala con:  pip install websockets", 4, C_RED)
        return
    pick = mp_pick_screen(screen, clock, archivos)
    if not pick:
        return
    path, char = pick
    me = make_player_info(path, char)
    while True:
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
        sess.close()
        AUDIO_MGR.play_music("music_menu")


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
        t = font_t.render("⚔  FILE SMASH  ⚔", True, C_YELLOW)
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
            _l2 = font_xs.render(f"Vel x{_pr['speed']:.2f}  Peso x{_pr['weight']:.2f}  Daño x{_pr['dmg']:.2f}",
                                 True, C_CYAN)
            screen.blit(_l1, (60, WIN_H - 66))
            screen.blit(_l2, (60, WIN_H - 50))

        pygame.draw.rect(screen, C_ORANGE, btn_start, border_radius=8)
        pygame.draw.rect(screen, C_YELLOW, btn_start, 2, border_radius=8)
        btn_txt = "▶  INICIAR" + (
            f"  ({os.path.basename(archivos[selected])[:20]})"
            if selected is not None else "  (todo IA)")
        btl = font_b.render(btn_txt, True, C_DARK)
        screen.blit(btl, btl.get_rect(center=btn_start.center))

        enter_lbl = font_xs.render("o presiona ENTER para iniciar", True, C_GRAY)
        screen.blit(enter_lbl, enter_lbl.get_rect(center=(WIN_W//2, WIN_H-8)))

        pygame.display.flip()
        clock.tick(FPS)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    AUDIO_MGR.stop_music()
                    return selected, char_assign
                if ev.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()
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

        # Dibujar
        draw_stage(screen, platforms)
        for f in fighters: f.draw(screen)
        draw_hud(screen, fighters, round_num, total_rounds)

        # Ganador
        alive_now = [f for f in fighters if f.alive]
        if len(alive_now) <= 1:
            winner = alive_now[0] if alive_now else None
            if winner:
                for _ in range(FPS*2):
                    draw_stage(screen, platforms)
                    winner.draw(screen)
                    draw_hud(screen, fighters, round_num, total_rounds)
                    msg = font_med.render(f"🏆  {winner.name[:40]}  GANA!", True, C_YELLOW)
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
    player_idx, char_assign = menu(screen, clock, archivos)
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
            lbl = font_big.render(f"👑  {campeon[:40]}", True, C_YELLOW)
            screen.blit(lbl, lbl.get_rect(center=(WIN_W//2, WIN_H//2+40)))
            sub = font_med.render("¡CAMPEÓN ABSOLUTO!  —  ESC para salir", True, C_ORANGE)
            screen.blit(sub, sub.get_rect(center=(WIN_W//2, WIN_H//2+80)))
            pygame.display.flip(); clock.tick(FPS)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT or (
                   ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                    done = True


def info_window(lines, secs=25):
    """Ventana simple con un aviso. Sirve tambien en el .exe, que no tiene consola."""
    pygame.init()
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
                     "Pon ahi COPIAS de los archivos que van a pelear (el perdedor se borra en VS CPU)",
                     "y vuelve a abrir el juego."])
        return

    archivos = sorted([
        os.path.join(PVP_FOLDER, f)
        for f in os.listdir(PVP_FOLDER)
        if os.path.isfile(os.path.join(PVP_FOLDER, f))
    ])
    if len(archivos) < 1:
        info_window(["La carpeta PVP esta vacia:", PVP_FOLDER, "",
                     "Pon al menos 1 archivo (2 o mas para jugar contra CPUs) y vuelve a abrir el juego."])
        return

    pygame.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("⚔ FILE SMASH ⚔")
    clock  = pygame.time.Clock()
    AUDIO_MGR = AudioManager()

    while True:
        mode = mode_screen(screen, clock, len(archivos))
        if mode == "cpu":
            play_cpu_mode(screen, clock, archivos)
            break
        elif mode == "mp":
            multiplayer_menu(screen, clock, archivos)
        else:
            break
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