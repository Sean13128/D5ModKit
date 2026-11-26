/* d5sound.inc.c -- the silence switch for agent launches (included by d5auto.c).
 *
 * Sean, 2026-10-27: "when agents launch or test the live game, it must not make sound".  macOS has no
 * per-app mute and no per-app audio tool is installed, so the mute is done inside the game, in memory:
 *
 *   the four volume masters are the float at +0 of four manager objects, reached through the globals
 *   0x140bd7b60 BGM / 0x140bd7b68 message voice / 0x140bd7b70 SE / 0x140bd7b78 unit voice.  Every play
 *   multiplies its own volume by its manager's master (sound_bgm_set_volume 0x1403f51b0,
 *   sound_msg_play 0x1403f5b60, se_update 0x1403f68d0, voice_update 0x1403f7600), so a master of 0 is
 *   silence for everything played afterwards.
 *
 *   the game's own setters take the Options value (0..10) and write master = value / 10.0:
 *   0x140226d30 BGM (then re-applies to the playing track via sound_bgm_set_volume),
 *   0x140226e30 message voice, 0x140227320 SE, 0x140227640 unit voice.  This is exactly what the options
 *   screen calls (sub_1402724a0, options 20..23), so it is the game's own path, not a poke at a guessed
 *   field.
 *
 * WHEN IT TAKES EFFECT (SILENTSHIP, 2026-10-28) -- the first sound, not the first command:
 *
 *   a) at boot the four managers are constructed with master = 1.0f (0x1400639f0 BGM, 0x140063ba0 msg,
 *      0x140063a90 SE, 0x140063c50 voice, in that order, from the sound init at 0x14013f1d0); NOTHING derives
 *      them from the Options at boot -- the only derivation in the game is lifecycle_flows_load_apply
 *      0x1401cc6c0, which runs on a save load.  So the masters have to go to 0 as soon as they exist:
 *      sound_tick() does it on the first frame all four managers are there, and this hook runs at the first
 *      call of the per-frame update (0x140221DBF, the exe patch's site), before that frame's script/talk VM
 *      and sound updates.
 *   b) a save load re-derives all four from the Options (lifecycle_flows_load_apply: four
 *      "movsx eax, byte [option 20/21/22/23]" reads at 0x1401cc6d3 / 0x1401cc71f / 0x1401cc73e / 0x1401cc75b,
 *      each followed by "... / 10.0 -> *(float*)mgr").  The harness loads a save on every run, and a play in
 *      the same load frame would be audible.  While silent those four reads are patched in memory to
 *      "xor eax,eax" + 5 nops, so the derivation itself computes 0 and no play in that call tree can see a
 *      non-zero master.  The original 7 bytes are kept and written back when silent is turned off.
 *   c) every frame after that, sound_tick() reads the four masters and, if any is non-zero (an Options
 *      change, a second derivation, a re-created manager), re-applies 0 and stops what is playing.
 *
 * Nothing on disk is touched: the Options bytes (0x14699f9fa, option i at +i -- 20..23 are these four
 * volumes) are only ever *read*, so a later Options save writes the player's real values back, and with
 * [debug] remote=1 the runtime blocks save writes anyway.  Sean's SystemSave/AutoSave cannot change.
 *
 * Movie audio is NOT covered: the movies (Movie/dis5_*.wmv) are played by Media Foundation (0x1408958d0
 * loads Mfplat.dll and Mf.dll and registers the "MovieDrawWin" window), which renders its own audio outside
 * these four managers, so no master reaches it.  Nothing in an agent run starts one -- the boot state only
 * constructs the movie object (SILENTSHIP-REPORT.md, "Movie/cutscene audio").
 *
 * When it is on: [audio] silent=1 in d5auto.ini, or "auto" (the default) with [debug] remote=1 -- a
 * pipe-connected game.  A person playing the game has remote=0 (remote=1 blocks save writes, so it is not
 * a play configuration) and therefore keeps their sound.  "silent off" restores the Options values and the
 * unpatched derivation immediately.
 *
 * Builds: every address here was read in the Steam build 9460a641... (the pinned exe; proof_silent.py).
 * The rest of the kit names the 2018 build's addresses and has them translated by d5lib/exemap; these are
 * this build's numbers and are identity entries in that build's map, so the feature is compiled in only
 * for this build and answers "not available" anywhere else instead of calling an address that may be a
 * different function there.
 */
static int snd_want(void);             /* defined below, used by sound_report */

#if defined(D5_BUILD_9460A6411699)

#define VA_SND_BGM_MGR    0x140bd7b60ULL   /* float master at +0 (audio_runtime.md 1.1) */
#define VA_SND_MSG_MGR    0x140bd7b68ULL   /* +0 master, 1.2 */
#define VA_SND_SE_MGR     0x140bd7b70ULL   /* +0 master, 1.3 */
#define VA_SND_VOICE_MGR  0x140bd7b78ULL   /* +0 master, 1.4 */
#define VA_SND_SET_BGM    0x140226d30ULL   /* int options value -> master, re-applies the BGM */
#define VA_SND_SET_MSG    0x140226e30ULL
#define VA_SND_SET_SE     0x140227320ULL
#define VA_SND_SET_VOICE  0x140227640ULL
#define VA_SND_SE_STOP_ALL    0x1403f7210ULL   /* in-flight SE would keep playing at the old volume */
#define VA_SND_MSG_STOP_ALL   0x1403f6060ULL
#define VA_SND_VOICE_STOP_ALL 0x14018c970ULL
#define VA_SND_OPTIONS    0x14699f9faULL   /* u8 option[i] at +i; 20..23 = BGM, SE, msg, voice (0..10) */

/* lifecycle_flows_load_apply 0x1401cc6c0 derives all four masters from the Options on a save load:
 * "movsx eax, byte [option]" (0f be 05 disp32, 7 bytes) then "... / 10.0 -> *(float*)mgr".  While silent
 * those four reads become "xor eax,eax" + 5 nops, so the derivation writes 0. */
#define VA_SND_OPT_READ_BGM   0x1401cc6d3ULL   /* option 20 */
#define VA_SND_OPT_READ_MSG   0x1401cc71fULL   /* option 22 */
#define VA_SND_OPT_READ_VOICE 0x1401cc73eULL   /* option 23 */
#define VA_SND_OPT_READ_SE    0x1401cc75bULL   /* option 21 */
#define SND_OPT_READ_LEN 7
static const unsigned char SND_OPT_READ_ZERO[SND_OPT_READ_LEN] = {0x31, 0xc0, 0x90, 0x90, 0x90, 0x90, 0x90};
static const unsigned long long snd_opt_reads[4] = {VA_SND_OPT_READ_BGM, VA_SND_OPT_READ_MSG,
                                                    VA_SND_OPT_READ_VOICE, VA_SND_OPT_READ_SE};
static const char *const snd_opt_names[4] = {"bgm", "msg", "voice", "se"};
static unsigned char g_snd_opt_orig[4][SND_OPT_READ_LEN];
static int g_snd_clamped;                  /* the four derivation reads are patched to 0 */

typedef void (*SND_SET_FN)(int);

/* g_sound_want / g_sound_applied / g_sound_frame / g_sound_engaged / g_sound_asserts are declared with
   the other settings in d5auto.c */

/* the manager object behind a global, or 0 before its constructor has run.
 *
 * LIVE7 (2026-10-28): the four manager objects are HEAP allocations, not image data -- read live through the
 * pipe, bgm 0x76c6540 / msg 0x76c65a0 / se 0xa603520 / voice 0xa603da0 against an image range of
 * 0x140000000..0x148125000.  The old `in_image(m, 4)` test therefore rejected every one of them: snd_ready()
 * was false forever, snd_set_masters() returned early, sound_tick() never engaged and "silent on" was a no-op
 * (silent_status answered -1.000 for all four masters).  The *global* must still be an image address (it is a
 * module global), but the object behind it only has to be committed, readable memory, which is exactly what
 * `readable()` (VirtualQuery, d5auto.c) answers -- the same test d5color/d5ctl already use on the heap unit
 * records.  snd_ptr_ok() is the predicate on its own so tests/test_silent.py can compile and run this exact
 * source text against heap pointers (tests heap-like and NULL cases without a game). */
static int snd_ptr_ok(const void *m) {
    return readable(m, 4);                 /* committed, readable, not PAGE_NOACCESS/PAGE_GUARD, non-NULL */
}

static void *snd_mgr(unsigned long long va) {
    void **pp = (void **)G(va);
    if (!in_image(pp, sizeof(void *)) || !readable(pp, sizeof(void *))) return 0;
    void *m = *pp;
    return snd_ptr_ok(m) ? m : 0;
}

static int snd_option(int i) {
    unsigned char *p = (unsigned char *)G(VA_SND_OPTIONS + i);
    int v = in_image(p, 1) ? *p : 10;
    return v < 0 ? 0 : v > 10 ? 10 : v;
}

static float snd_master(unsigned long long va) {
    void *m = snd_mgr(va);
    return m ? *(volatile float *)m : -1.0f;
}

static int snd_ready(void) {
    return snd_mgr(VA_SND_BGM_MGR) && snd_mgr(VA_SND_MSG_MGR) &&
           snd_mgr(VA_SND_SE_MGR) && snd_mgr(VA_SND_VOICE_MGR);
}

/* master = value (0..10 -> 0.0..1.0) for all four; 0 is silence */
static int snd_set_masters(int value) {
    if (!snd_ready()) return 0;                                    /* not constructed yet */
    ((SND_SET_FN)G(VA_SND_SET_BGM))(value);
    ((SND_SET_FN)G(VA_SND_SET_MSG))(value);
    ((SND_SET_FN)G(VA_SND_SET_SE))(value);
    ((SND_SET_FN)G(VA_SND_SET_VOICE))(value);
    return 1;
}

/* every master back to the Options value it is supposed to have (20 BGM, 21 SE, 22 msg, 23 voice) */
static int snd_restore_masters(void) {
    if (!snd_ready()) return 0;
    ((SND_SET_FN)G(VA_SND_SET_BGM))(snd_option(20));
    ((SND_SET_FN)G(VA_SND_SET_SE))(snd_option(21));
    ((SND_SET_FN)G(VA_SND_SET_MSG))(snd_option(22));
    ((SND_SET_FN)G(VA_SND_SET_VOICE))(snd_option(23));
    return 1;
}

/* everything still sounding stops now (a master of 0 only silences what plays next) */
static void snd_stop_inflight(void) {
    if (snd_mgr(VA_SND_SE_MGR)) ((void (*)(void))G(VA_SND_SE_STOP_ALL))();
    if (snd_mgr(VA_SND_MSG_MGR)) ((void (*)(void))G(VA_SND_MSG_STOP_ALL))();
    if (snd_mgr(VA_SND_VOICE_MGR)) ((void (*)(void))G(VA_SND_VOICE_STOP_ALL))();
}

/* clamp / unclamp the save-load derivation: master = option / 10.0 becomes 0 / 10.0 */
static void snd_clamp_derivation(int on) {
    if (on == g_snd_clamped) return;
    int n = 0;
    for (int i = 0; i < 4; i++) {
        unsigned char *p = (unsigned char *)G(snd_opt_reads[i]);
        if (!in_image(p, SND_OPT_READ_LEN) || p[0] != 0x0f || p[1] != 0xbe || p[2] != 0x05) {
            logf_("silent: the %s derivation site (%llx) is not as expected - not patched", snd_opt_names[i],
                  snd_opt_reads[i]);
            continue;
        }
        if (on) {
            memcpy(g_snd_opt_orig[i], p, SND_OPT_READ_LEN);
            if (write_code(snd_opt_reads[i], SND_OPT_READ_ZERO, SND_OPT_READ_LEN)) n++;
        } else {
            if (write_code(snd_opt_reads[i], g_snd_opt_orig[i], SND_OPT_READ_LEN)) n++;
        }
    }
    g_snd_clamped = on ? (n == 4) : 0;
    logf_("silent: save-load derivation %s (%d/4 sites)", on ? "clamped" : "restored", n);
}

/* any master that should be 0 but is not: a re-derivation, an Options change, a re-created manager */
static int snd_drifted(void) {
    if (!snd_ready()) return 0;
    return snd_master(VA_SND_BGM_MGR) != 0.0f || snd_master(VA_SND_MSG_MGR) != 0.0f ||
           snd_master(VA_SND_SE_MGR) != 0.0f || snd_master(VA_SND_VOICE_MGR) != 0.0f;
}

static int sound_available(void) { return 1; }

/* on: clamp the derivation, masters 0, stop what is playing.  off: unclamp, every master back to Options. */
static int sound_apply(int on) {
    if (on) {
        snd_clamp_derivation(1);                   /* first: the load path can no longer raise the masters */
        if (!snd_set_masters(0)) return 0;
        snd_stop_inflight();
        g_sound_applied = 1;
    } else {
        snd_clamp_derivation(0);
        if (!snd_restore_masters()) return 0;
        g_sound_applied = 0;
    }
    g_sound_frame = (long)g_frame;
    return 1;
}

/* "silent status": what was asked, what is in force, and the four masters read back */
static void sound_report(char *out, size_t n) {
    snprintf(out, n, "{\"available\":1,\"want\":%d,\"applied\":%d,\"bgm\":%.3f,\"msg\":%.3f,\"se\":%.3f,"
             "\"voice\":%.3f,\"options\":[%d,%d,%d,%d],\"remote\":%d,\"clamped\":%d,\"engaged\":%ld,"
             "\"asserts\":%d,\"frame\":%ld}",
             snd_want(), g_sound_applied, snd_master(VA_SND_BGM_MGR), snd_master(VA_SND_MSG_MGR),
             snd_master(VA_SND_SE_MGR), snd_master(VA_SND_VOICE_MGR),
             snd_option(20), snd_option(21), snd_option(22), snd_option(23), g_remote ? 1 : 0,
             g_snd_clamped, g_sound_engaged, g_sound_asserts, (long)g_frame);
}

#else   /* another build of the game: this switch's addresses were only ever verified in 9460a641... */

static int sound_available(void) { return 0; }
static int sound_apply(int on) { (void)on; return 0; }
static void sound_report(char *out, size_t n) {
    snprintf(out, n, "{\"available\":0,\"want\":%d,\"applied\":0,\"clamped\":0,\"engaged\":-1,\"asserts\":0,"
             "\"error\":\"the silence switch is wired for the Steam build 9460a641... only\"}", snd_want());
}

#endif

static int snd_want(void) {
    if (g_sound_want >= 0) return g_sound_want;
    return g_remote ? 1 : 0;           /* auto: a pipe-connected game is a test game */
}

/* the pipe command: silent on | off | status -> 1 = set, 0 = not available / not mounted yet */
static int sound_set(int on) {
    g_sound_want = on ? 1 : 0;
    int r = sound_apply(on);
    logf_("silent %s%s", on ? "ON" : "OFF",
          r ? "" : sound_available() ? " (the sound system is not mounted yet)" : " (not available for this build)");
    return r;
}

static void sound_reset(void) {
    g_sound_applied = -1;
    g_sound_frame = 0;
    g_sound_engaged = -1;
    g_sound_asserts = 0;
}

/* Every frame: clamp the load-path derivation, engage on the first frame the four managers exist, then hold
   the masters at 0 for the whole session (a save load or an Options change is undone within one frame). */
static void sound_tick(void) {
    int want = snd_want();
    if (!want) {
        if (g_sound_applied != 0) sound_apply(0);
        return;
    }
#if defined(D5_BUILD_9460A6411699)
    if (!g_snd_clamped) snd_clamp_derivation(1);       /* as early as the first tick, managers or not */
#endif
    if (g_sound_applied != 1) {
        if (!sound_apply(1)) return;                   /* the managers are not constructed yet: retry next frame */
        g_sound_engaged = (long)g_frame;
        logf_("silent: engaged at frame %ld (four masters 0, save-load derivation clamped)", g_sound_engaged);
        return;
    }
#if defined(D5_BUILD_9460A6411699)
    if (snd_drifted()) {                               /* a load or an Options change raised them again */
        float bgm = snd_master(VA_SND_BGM_MGR), msg = snd_master(VA_SND_MSG_MGR);
        float se = snd_master(VA_SND_SE_MGR), voice = snd_master(VA_SND_VOICE_MGR);
        sound_apply(1);
        g_sound_asserts++;
        if (g_sound_asserts <= 8 || (g_sound_asserts % 60) == 0)
            logf_("silent: re-asserted at frame %ld (was bgm %.2f msg %.2f se %.2f voice %.2f; #%d)",
                  (long)g_frame, bgm, msg, se, voice, g_sound_asserts);
    }
#endif
}
