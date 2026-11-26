/* Window hide (WINHIDE1, 2026-11-11): keep the game window out of Sean's workspace from inside the process, with no
 * macOS permission (the AppleScript hider needs Automation for System Events and has failed with -1743 since 11-08).
 *   win offscreen [X Y]   SetWindowPos to X,Y (default: right of the whole virtual screen); size, z-order, focus and
 *                         visibility unchanged, so the game sees a normal visible, un-minimised window
 *   win hide              ShowWindow(SW_HIDE); no WM_SIZE(SIZE_MINIMIZED), so the game's minimised flag (+0x9a0 == 2,
 *                         which game_frame reads) is not set
 *   win show              back to the position it had before the first offscreen/hide, shown without activating
 *   win state             mode, visible, iconic, current rect
 * The state lives in this process only: the next launch always opens a normal window. The game's window runs its own
 * message loop thread, so these calls from the pipe thread are synchronous cross-thread calls. */
static int g_wh_mode;                 /* 0 normal, 1 offscreen, 2 hidden */
static RECT g_wh_orig;                /* the rect before the first move */

static int winhide_cmd(HWND w, int argc, char **argv, char *o, size_t n) {
    const char *m = argc > 1 ? argv[1] : "state";
    if (!w) { snprintf(o, n, "{\"error\":\"no game window\"}"); return 0; }
    if (!strcmp(m, "offscreen") || !strcmp(m, "hide")) {
        RECT r;
        if (!g_wh_mode) { GetWindowRect(w, &g_wh_orig); }
        if (!strcmp(m, "hide")) {
            ShowWindow(w, SW_HIDE);
            g_wh_mode = 2;
        } else {
            int x = GetSystemMetrics(SM_XVIRTUALSCREEN) + GetSystemMetrics(SM_CXVIRTUALSCREEN) + 2000;
            int y = GetSystemMetrics(SM_YVIRTUALSCREEN);
            if (argc > 3) { x = atoi(argv[2]); y = atoi(argv[3]); }
            if (g_wh_mode == 2) ShowWindow(w, SW_SHOWNA);
            SetWindowPos(w, NULL, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
            g_wh_mode = 1;
        }
        GetWindowRect(w, &r);
        snprintf(o, n, "{\"ok\":1,\"mode\":%d,\"x\":%ld,\"y\":%ld}", g_wh_mode, (long)r.left, (long)r.top);
    } else if (!strcmp(m, "show")) {
        if (g_wh_mode) {
            ShowWindow(w, SW_SHOWNA);
            SetWindowPos(w, NULL, g_wh_orig.left, g_wh_orig.top, 0, 0,
                         SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
            g_wh_mode = 0;
        }
        snprintf(o, n, "{\"ok\":1,\"mode\":0}");
    } else if (!strcmp(m, "state")) {
        RECT r;
        GetWindowRect(w, &r);
        snprintf(o, n, "{\"mode\":%d,\"visible\":%d,\"iconic\":%d,\"x\":%ld,\"y\":%ld,\"w\":%ld,\"h\":%ld}", g_wh_mode,
                 IsWindowVisible(w) ? 1 : 0, IsIconic(w) ? 1 : 0, (long)r.left, (long)r.top, (long)(r.right - r.left),
                 (long)(r.bottom - r.top));
    } else {
        snprintf(o, n, "{\"error\":\"win offscreen [X Y] | hide | show | state\"}");
        return 0;
    }
    return 1;
}
