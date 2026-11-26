#include <windows.h>
#include "d5winhide.h"
static void run(const char *a, const char *b, const char *c, const char *d) {
    char *argv[4] = {"win", (char *)a, (char *)b, (char *)c}, o[256];
    int argc = d ? 4 : c ? 4 : b ? 3 : a ? 2 : 1; (void)d;
    printf("> %s\n", a ? a : "(none)");
    winhide_cmd((HWND)1, argc, argv, o, sizeof o);
    printf("%s\n", o);
}
int main(void) {
    char o[64];
    printf("null:%d\n", winhide_cmd(NULL, 2, (char *[]){"win", "hide"}, o, sizeof o));
    run("state", 0, 0, 0);
    run("offscreen", 0, 0, 0);
    run("offscreen", "-5000", "10", 0);   /* a second move keeps the first original */
    run("show", 0, 0, 0);
    run("hide", 0, 0, 0);
    run("offscreen", 0, 0, 0);            /* hidden -> offscreen shows it first */
    run("show", 0, 0, 0);
    run("show", 0, 0, 0);                 /* idempotent */
    run("bogus", 0, 0, 0);
    return 0;
}
