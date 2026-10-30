// SPDX-License-Identifier: GPL-2.0-or-later
/* C interface of the GPU library (gpu/): the command processor and Vulkan renderer,
 * GnmDriver, VideoOut and kernel event queues, adapted to the native loader. */
#ifndef SKYRENDER_H
#define SKYRENDER_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    const char *title;          /* window title */
    const char *serial;         /* CUSA id, names the pipeline cache */
    const char *user_dir;       /* pipeline cache/logs directory */
    uint32_t sdk_version;       /* from the eboot's procparam */
    uint32_t psf_attributes;    /* param.sfo ATTRIBUTE */
    int32_t width, height;      /* initial window size */
} SkyRenderConfig;
/* Registers kernel event queues (needed with or without graphics). */
void skyrender_register_kernel(void);
/* Creates window, Vulkan device, presenter and GPU command processor. */
int skyrender_init(const SkyRenderConfig *config);
/* Function for an imported NID ("NID#lib#mod"), or 0 when the GPU library does not provide it. */
uintptr_t skyrender_resolve(const char *scoped_nid);
/* Called first by the loader's SIGSEGV handler: 1 when a GPU page-tracking fault was handled. */
int skyrender_handle_fault(void *ucontext, void *address);
/* SKY_RENDERER_WRITE_LOG=1: prints the logged GPU-side writes to guest memory near the fault. */
void skyrender_dump_guest_writes(void *ucontext);
/* Keyboard text entry through the game window (IME dialog). begin returns 0 when
 * no window exists; poll returns 0 typing, 1 confirmed, 2 cancelled (UTF-8 text). */
int skyrender_text_input_begin(const char *initial_utf8, const char *prompt_utf8);
int skyrender_text_input_poll(char *out_utf8, uint64_t size);
/* 1 while the in-game settings menu is open: the game's pad input is held neutral. */
int skyrender_overlay_captures_input(void);
/* Mouse look (runtime_pad.c): the window takes the mouse when it is clicked (relative mode) and
 * lets it go on F1, losing focus or the menu opening. take: motion (pixels) and wheel notches
 * since the last call, reset; captured: 1 while the window holds it; enable: mouse_look=0 in
 * renderer.ini keeps the window from taking it. */
void skyrender_mouse_take(double *dx, double *dy, int *wheel_up, int *wheel_down);
int skyrender_mouse_captured(void);
/* Asks the window to take the mouse (relative mode, as a click in the game does); the window
 * thread does it. */
void skyrender_mouse_capture(void);
void skyrender_mouse_look_enable(int enabled);
/* A module's look at the window's events first (an SDL_Event and the SDL_Window, on the window
 * thread): nonzero takes the event (the port and the game do not see it). Up to 4. */
typedef int (*SkyRenderEventFilter)(const void *sdl_event, void *sdl_window);
void skyrender_add_event_filter(SkyRenderEventFilter filter);
/* A module's menu pointer: nonzero while the game shows a menu the mouse points into. The window
 * then lets the mouse go and shows the cursor, and takes the mouse back after (as it had it).
 * Up to 4; pointer_wanted: any of them says so. */
typedef int (*SkyRenderPointerQuery)(void);
void skyrender_add_pointer_query(SkyRenderPointerQuery query);
int skyrender_pointer_wanted(void);
/* A module's changes to the pad state the game reads (runtime_pad.c, after the host's input and
 * the scripted one): the buttons (PS4 bits); the sticks (lx ly rx ry) as they are. Up to 4. */
typedef void (*SkyRenderPadFilter)(uint32_t *buttons, const uint8_t *sticks);
void skyrender_add_pad_filter(SkyRenderPadFilter filter);
void skyrender_filter_pad(uint32_t *buttons, const uint8_t *sticks);
/* The shown frame's width / height (the display buffer's; the window letterboxes it). */
float skyrender_frame_aspect(void);
/* A line of text over the game, near the bottom, until called with NULL (any thread). */
void skyrender_overlay_banner(const char *utf8);
/* Number of symbols registered by the vendored libraries (diagnostics). */
unsigned skyrender_symbol_count(void);
#ifdef __cplusplus
}
#endif
#endif
