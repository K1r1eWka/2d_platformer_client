# Run: python test_online_game.py <client_id> [room_id]

import json
import sys
import threading

import pygame
from websockets.sync.client import connect

from screen_presenter import present

SERVER = "ws://127.0.0.1:8000"

# Virtual field the whole game is drawn at, then scaled up to the real
# screen — keeps the field identical for every player regardless of monitor.
# All clients in a room must use the same preset, or coordinates mean
# different things; the client warns if it sees a mismatched one.
FIELDS = {
    "fhd": (1920, 1080),
}
FIELD = "fhd"
VIRTUAL_W, VIRTUAL_H = FIELDS[FIELD]

TILE = 16                    # tile size; everything else is derived from it
PLAYER_W, PLAYER_H = 24, 32  # 1.5 tiles wide, 2 tiles tall
GROUND_H = 2 * TILE          # ground thickness at the bottom of the arena

# Tuned for a 480x270 field and scaled with VIRTUAL_H, so jump height and
# platform reach stay proportional at any field size.
PHYS = VIRTUAL_H / 270
SPEED = 2.0 * PHYS
GRAVITY = 0.45 * PHYS
JUMP = -7.0 * PHYS
FPS = 60

SKY_COLOR = (110, 180, 230)
DIRT_COLOR = (150, 110, 70)
GRASS_COLOR = (90, 170, 80)
PLAYER_COLOR = (230, 190, 60)  
OTHER_PLAYER_COLOR = (90, 160, 230)

# Background thread fills this; the game loop drains it once per frame.
incoming = []


# Reads server messages on a background thread so blocking IO doesn't freeze the game.
def receive_loop(ws):
    try:
        for raw in ws:
            incoming.append(json.loads(raw))
    except Exception:
        pass
    incoming.append({"type": "disconnected"})


# Starting x by client id, spread across the arena so players don't stack.
def spawn_x(client_id):
    slots = 6
    index = sum(client_id.encode()) % slots
    return float(round(VIRTUAL_W / (slots + 1) * (index + 1) - PLAYER_W / 2))


# Arena: ground plus one jumpable platform in the center.
# Positions are fractions of the field size, so the layout looks the same at any preset.
# f means fraction of the field size (0.0 to 1.0) 
def build_platforms():
    ground = pygame.Rect(0, VIRTUAL_H - GROUND_H, VIRTUAL_W, GROUND_H)

    fx, fy, fw = 0.40, 0.80, 0.25
    left = round(fx * VIRTUAL_W / TILE) * TILE
    top = round(fy * VIRTUAL_H / TILE) * TILE
    width = round(fw * VIRTUAL_W / TILE) * TILE
    middle = pygame.Rect(left, top, width, TILE)

    return [ground, middle]


# Ground block with a grass strip on top.
def draw_platform(surface, rect):
    pygame.draw.rect(surface, DIRT_COLOR, rect)
    pygame.draw.rect(surface, GRASS_COLOR, (rect.x, rect.y, rect.width, 4))


def player_rect(x, y):
    return pygame.Rect(int(x), int(y), PLAYER_W, PLAYER_H)


def draw_player(surface, x, y, color):
    pygame.draw.rect(surface, color, player_rect(x, y))


def desktop_size():
    try:
        return pygame.display.get_desktop_sizes()[0]
    except Exception:
        info = pygame.display.Info()
        return info.current_w, info.current_h


def make_screen(fullscreen):
    desk_w, desk_h = desktop_size()

    if fullscreen:
        return pygame.display.set_mode((desk_w, desk_h))

    width = min(VIRTUAL_W * 2, int(desk_w * 0.9))
    height = min(VIRTUAL_H * 2, int(desk_h * 0.9))
    return pygame.display.set_mode((width, height))


def main_online():
    client_id = sys.argv[1] if len(sys.argv) > 1 else input("client_id: ").strip()
    room_id = sys.argv[2] if len(sys.argv) > 2 else "room1"

    ws = connect(f"{SERVER}/ws/{room_id}?client_id={client_id}")
    threading.Thread(target=receive_loop, args=(ws,), daemon=True).start()

    # Tell others our field preset so a mismatch can be detected.
    def announce_field():
        try:
            ws.send(json.dumps({"type": "hello", "field": FIELD}))
        except Exception:
            pass

    announce_field()

    pygame.init()
    fullscreen = True
    screen = make_screen(fullscreen)
    pygame.display.set_caption(f"platformer — {client_id}")
    world = pygame.Surface((VIRTUAL_W, VIRTUAL_H))
    clock = pygame.time.Clock()

    platforms = build_platforms()

    # Position as floats: Rect only holds ints and would drop sub-pixel gravity.
    x = spawn_x(client_id)
    y = float(VIRTUAL_H - GROUND_H - PLAYER_H)
    vy = 0.0
    on_ground = True

    others = {}   # client_id -> {"x", "y", "state"}
    last_sent_snapshot = None
    running = True
    state = "idle"

    while running:
        # 1. Input
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_f:
                    fullscreen = not fullscreen
                    screen = make_screen(fullscreen)
                elif event.key == pygame.K_SPACE and on_ground:
                    vy = JUMP
                    on_ground = False

        # 2. Move and collide with platforms. X then Y separately, otherwise
        # we can't tell which side we hit from.
        keys = pygame.key.get_pressed()
        dx = 0.0
        if keys[pygame.K_a]:
            dx -= SPEED
        if keys[pygame.K_d]:
            dx += SPEED

        x = max(0.0, min(x + dx, VIRTUAL_W - PLAYER_W))
        for platform in platforms:
            if player_rect(x, y).colliderect(platform):
                if dx > 0:
                    x = float(platform.left - PLAYER_W)
                elif dx < 0:
                    x = float(platform.right)

        vy += GRAVITY
        y += vy
        on_ground = False
        for platform in platforms:
            if not player_rect(x, y).colliderect(platform):
                continue
            if vy > 0:
                y = float(platform.top - PLAYER_H)
                on_ground = True
            elif vy < 0:
                y = float(platform.bottom)
            vy = 0.0

        state = "air" if not on_ground else ("run" if dx else "idle")

        # 3. Drain server messages: update state only, drawing happens below.
        while incoming:
            msg = incoming.pop(0)
            kind = msg.get("type")
            who = msg.get("client_id", "?")

            if kind == "move":
                # an unknown id's first move message creates its entry
                others[who] = {
                    "x": msg["x"],
                    "y": msg["y"],
                    "state": msg.get("state", "idle"),
                }
            elif kind == "player_joined":
                # newcomer hasn't seen us yet — force a resend
                last_sent_snapshot = None
                announce_field()
            elif kind == "player_left":
                others.pop(who, None)

        # 4. Draw: sky, platforms, other players, self
        world.fill(SKY_COLOR)

        # Draw all platforms first so players appear on top
        for platform in platforms:
            draw_platform(world, platform)

        # Draw other players next so they appear above platforms but below the local player
        for other in others.values():
            draw_player(world, other["x"], other["y"], OTHER_PLAYER_COLOR)

        draw_player(world, x, y, PLAYER_COLOR)

        present(screen, world)

        # 5. Send our state only when it changed, else we'd flood the server
        # at 60 packets/sec; state is needed so others animate correctly.
        current_snapshot = (round(x), round(y), state)
        if current_snapshot != last_sent_snapshot:
            try:
                ws.send(json.dumps({
                    "type": "move",
                    "x": current_snapshot[0],
                    "y": current_snapshot[1],
                    "state": state,
                }))
            except Exception:
                pass
            last_sent_snapshot = current_snapshot

        clock.tick(FPS)

    pygame.quit()
    ws.close()


if __name__ == "__main__":
    main_online()
