/* Remote held keys retain their DirectInput scan-code indexing. */
static void d5_hold_di(unsigned char *state, const volatile unsigned char *held, int enabled) {
    if (!enabled) return;
    for (int i = 0; i < 256; ++i) if (held[i]) state[i] |= 0x80;
}
