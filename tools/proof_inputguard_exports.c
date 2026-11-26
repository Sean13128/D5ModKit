/* tools/proof_inputguard.py: the runtime core as built for the game + setters for the Unicorn proof (never shipped) */
#include "d5auto.c"

__declspec(dllexport) void proof_setup(int remote, int guard, int fake, void *oxi, void *odi, void *okbd) {
    g_remote = remote;
    g_input_guard = guard;
    g_fake_focus = fake;
    g_game_tid = 0;
    oXIGetState = (XIGetState_t)oxi;
    oGetDeviceStateA = (GetDeviceState_t)odi;
    oGetKeyboardState = (GetKeyboardState_t)okbd;
}
__declspec(dllexport) void proof_inject(int dik, int on) { g_dik[dik & 255] = (BYTE)on; }
__declspec(dllexport) void *proof_hook_pad(void) { return (void *)hkXIGetState; }
__declspec(dllexport) void *proof_hook_dia(void) { return (void *)hkGetDeviceStateA; }
__declspec(dllexport) long proof_count(int pad) { return pad ? g_guard_pad : g_guard_kb; }
