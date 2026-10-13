/* d5noauto.inc.c -- stand-ins for the Item World auto-battle (included by d5auto.c instead of d5pilot.inc.c,
 * d5di.inc.c and d5menu.inc.c when those aren't there: the shareable kit leaves the auto-battle out).
 * The rest of the runtime (outfit looks' colours, the character-row fixer, custom colour slots, the live skill
 * preview, the D5 Mod Kit's link) calls these.  auto_tick keeps the two jobs the auto-battle's tick does for
 * everyone: playing the link's injected keys, and installing the screen-state and screen-text hooks (d5ui.inc.c:
 * custom colour slots find the colour editor by its text, the link reads the screen). */
static int g_menu_key;
static int g_dep_on, g_nav, g_astate;           /* the dev link's state dump reads them */

static void auto_reset(void) {}
static void auto_tick(void) {
    keys_tick();
    static int hooks;
    if (!hooks) { hooks = 1; install_sm_hook(); install_text_hook(); }
}
static int di_unit_uses_ai(const UNIT *u) { (void)u; return 1; }
static void load_skill_data(void) {}
static void load_programs(void) {}
static void menu_tick(void) {}
static void menu_draw(IDXGISwapChain *sc) { (void)sc; }
static void menu_shutdown(void) {}
