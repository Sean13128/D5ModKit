/* Stub of the few Win32 calls d5winhide.h makes: each call is printed, so a test can check the sequence. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef void *HWND; typedef int BOOL; typedef struct { long left, top, right, bottom; } RECT;
#define SW_HIDE 0
#define SW_SHOWNA 8
#define SWP_NOSIZE 1
#define SWP_NOZORDER 4
#define SWP_NOACTIVATE 0x10
#define SWP_NOOWNERZORDER 0x200
#define SM_XVIRTUALSCREEN 76
#define SM_YVIRTUALSCREEN 77
#define SM_CXVIRTUALSCREEN 78
static RECT g_stub_rect = {100, 50, 1380, 770};
static int g_stub_vis = 1;
static int GetSystemMetrics(int i) { return i == SM_XVIRTUALSCREEN ? 0 : i == SM_YVIRTUALSCREEN ? 0 : 1920; }
static BOOL GetWindowRect(HWND w, RECT *r) { (void)w; *r = g_stub_rect; return 1; }
static BOOL IsWindowVisible(HWND w) { (void)w; return g_stub_vis; }
static BOOL IsIconic(HWND w) { (void)w; return 0; }
static BOOL ShowWindow(HWND w, int c) { (void)w; printf("ShowWindow %d\n", c); g_stub_vis = c != SW_HIDE; return 1; }
static BOOL SetWindowPos(HWND w, HWND a, int x, int y, int cx, int cy, unsigned f) {
    (void)w; (void)a;
    printf("SetWindowPos %d %d %d %d flags=%x\n", x, y, cx, cy, f);
    long dx = x - g_stub_rect.left, dy = y - g_stub_rect.top;
    g_stub_rect.left += dx; g_stub_rect.right += dx; g_stub_rect.top += dy; g_stub_rect.bottom += dy;
    return 1;
}
