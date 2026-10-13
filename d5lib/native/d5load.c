/* d5load.c -- d5auto.dll, the small loader the exe patch loads (d5lib/autobattle.py).
 *
 * The game calls d5_frame() once per frame.  The loader keeps the real code -- d5core.dll next to the exe -- in a
 * copy (d5core_live<N>.dll), so d5core.dll itself is never locked and can be replaced while the game runs: when the
 * core asks for it (core_frame() returns 1, e.g. after the test harness' "reload"), the loader shuts the core down
 * (it takes every hook out again), unloads it and loads the new d5core.dll. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

typedef int (*core_frame_t)(void);
typedef void (*core_shutdown_t)(void);
typedef void (*core_set_gen_t)(int);

static char g_dir[MAX_PATH];
static HMODULE g_core;
static core_frame_t p_frame;
static core_shutdown_t p_shutdown;
static int g_gen, g_failed;

static void load_core(void) {
    char src[MAX_PATH], dst[MAX_PATH];
    snprintf(src, sizeof src, "%sd5core.dll", g_dir);
    for (int i = 0; i < 8; i++) {                 /* leftovers of earlier runs / reloads */
        char old[MAX_PATH];
        snprintf(old, sizeof old, "%sd5core_live%d.dll", g_dir, i);
        DeleteFileA(old);
    }
    for (int tries = 0; tries < 8; tries++) {
        snprintf(dst, sizeof dst, "%sd5core_live%d.dll", g_dir, (g_gen + tries) % 8);
        if (CopyFileA(src, dst, FALSE)) break;
    }
    g_core = LoadLibraryA(dst);
    if (!g_core) { g_failed = 1; return; }
    p_frame = (core_frame_t)GetProcAddress(g_core, "core_frame");
    p_shutdown = (core_shutdown_t)GetProcAddress(g_core, "core_shutdown");
    core_set_gen_t set_gen = (core_set_gen_t)GetProcAddress(g_core, "core_set_gen");
    if (set_gen) set_gen(g_gen);
    if (!p_frame || !p_shutdown) { FreeLibrary(g_core); g_core = NULL; g_failed = 1; return; }
    g_gen++;
}

__declspec(dllexport) void d5_frame(void) {
    if (!g_core) {
        if (g_failed) return;
        load_core();
        if (!g_core) return;
    }
    if (p_frame() == 1) {                         /* the core wants to be reloaded */
        p_shutdown();
        FreeLibrary(g_core);
        g_core = NULL;
        p_frame = NULL;
        p_shutdown = NULL;
        load_core();
    }
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r) {
    (void)r;
    if (reason == DLL_PROCESS_ATTACH) {
        GetModuleFileNameA(h, g_dir, MAX_PATH);
        char *s = strrchr(g_dir, '\\');
        if (s) s[1] = 0;
        DisableThreadLibraryCalls(h);
    }
    return TRUE;
}
