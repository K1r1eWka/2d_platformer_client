# Scales the fixed-size virtual screen up to the player's real window.

import pygame


# Picks an image size that fits the monitor, plus a label for debugging.
# Uses an integer multiple while the virtual field fits the screen, else
# pixels would blur; shrinks fractionally if the field is bigger than screen.
def fit_to_screen(screen, virtual_w, virtual_h):
    screen_w, screen_h = screen.get_size()

    if screen_w >= virtual_w and screen_h >= virtual_h:
        scale = min(screen_w // virtual_w, screen_h // virtual_h)
        return virtual_w * scale, virtual_h * scale, f"x{scale}"

    factor = min(screen_w / virtual_w, screen_h / virtual_h)
    return int(virtual_w * factor), int(virtual_h * factor), f"x{factor:.2f}"


# Stretches the virtual world onto the real screen and centers it.
def present(screen, world):
    screen_w, screen_h = screen.get_size()
    virtual_w, virtual_h = world.get_size()
    width, height, _ = fit_to_screen(screen, virtual_w, virtual_h)

    screen.fill((0, 0, 0))
    screen.blit(
        pygame.transform.scale(world, (width, height)),
        ((screen_w - width) // 2, (screen_h - height) // 2),
    )
    pygame.display.flip()
