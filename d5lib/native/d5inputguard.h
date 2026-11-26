/* Input guard (INPUTGUARD1, 2026-11-09): while the harness drives the game ([debug] remote=1) the game takes input
 * only from the harness's injected presses.  How the game reads input (decomp, pinned Steam exe):
 *   keyboard  DirectInput GetDeviceState(256) every frame (0x14089d890 / input_raw_key 0x1408a02b0), device made with
 *             SetCooperativeLevel 6 = NONEXCLUSIVE|FOREGROUND (0x14089db90); GetKeyboardState only if that failed
 *   mouse     DirectInput GetDeviceState(0x14), also FOREGROUND
 *   pads      up to 32 slots found by EnumDevices(GAMECTRL) on a 1 s hot-plug thread (0x14089f570 -> 0x1408a1200);
 *             an XInput pad is read with XInputGetState (0x1408a06d0, import 0x1408d5738), any other with
 *             DirectInput Poll + GetDeviceState(0x50) (0x1408a0880), made with level 10 = NONEXCLUSIVE|BACKGROUND
 * XInput and a BACKGROUND joystick are read whatever window is in front, so a pad on the desk drives a hidden game.
 * These helpers say whether the real state carried input, and drop it; the hooks add the injected keys after. */
static volatile LONG g_guard_kb, g_guard_pad;     /* polls whose real keyboard/mouse or pad input was dropped */

static int guard_any(const unsigned char *p, unsigned n, unsigned char mask) {
    for (unsigned i = 0; i < n; i++) if (p[i] & mask) return 1;
    return 0;
}

/* keyboard (256 DIK or VK bytes, mask 0x80: a VK byte's bit 0 is a lock key's toggle) or mouse (DIMOUSESTATE[2],
 * mask 0xFF): drop everything; mask 0 = do not count (the read failed, or keys the harness injected are in it) */
static void guard_drop(unsigned char *p, unsigned n, unsigned char mask) {
    if (mask && guard_any(p, n, mask)) InterlockedIncrement(&g_guard_kb);
    memset(p, 0, n);
}

/* XINPUT_STATE: dwPacketNumber, then 12 bytes of buttons, triggers and sticks (0 = released and centred); counted
 * when a button or trigger is down or a stick is past XInput's own dead zone (7849: a resting stick is never 0) */
static void guard_xinput(unsigned char *st) {
    const short *stick = (const short *)(st + 8);
    int moved = 0;
    for (int i = 0; i < 4; i++) moved |= stick[i] > 7849 || stick[i] < -7849;
    if (guard_any(st + 4, 4, 0xFF) || moved) InterlockedIncrement(&g_guard_pad);
    memset(st + 4, 0, 12);
}

/* DIJOYSTATE / DIJOYSTATE2: the state is NOT rewritten to "neutral" (the game measures a stick's centre from its
 * third read, 0x1408a0880 +0xcc, and a zero POV is d-pad up): the read fails instead, and the game's own path for a
 * failed read reports no buttons and leaves the slot connected.  Counted when a button or the POV was down. */
static int guard_joy_is_state(unsigned long cb) { return cb == 0x50 || cb == 0x110; }
static void guard_joy_count(const unsigned char *js) {
    unsigned pov = *(const unsigned *)(js + 0x20);
    if (guard_any(js + 0x30, 32, 0x80) || (pov & 0xFFFF) != 0xFFFF) InterlockedIncrement(&g_guard_pad);
}
