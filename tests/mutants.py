"""Undo each fix on a copy of device/ and check that its test turns red.
usage: python3 tests/mutants.py   (env BB as for run.sh). Local check, not shipped.
"""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.join(HERE, "..", "device")

M = [
    ("cache: start despite failed mount", "t_cache_mount_fails", [
        ("soloist-svc.sh", 'setup_cache || { log "no tmpfs cache: not starting Soloist"; cleanup 1; }', "setup_cache"),
        ("soloist-svc.sh", 'cache_mounted || { log "cache tmpfs is gone: not starting Soloist"; break; }', ":"),
    ]),
    ("pulse: start without socket", "t_pulse_never_up", [
        ("soloist-svc.sh", 'ensure_pulse || { log "PulseAudio did not come up: not starting Soloist"; cleanup 1; }', "ensure_pulse"),
        ("soloist-svc.sh", 'ensure_pulse || { log "PulseAudio did not come up: not starting Soloist"; break; }', "ensure_pulse"),
    ]),
    ("p2p0: any first IPv4", "t_p2p0_keeps_non_ll", [
        ("soloist-svc.sh", r"inet \(169\.254\.[0-9]*\.[0-9]*\/[0-9]*\)", r"inet \([0-9.]*\/[0-9]*\)"),
    ]),
    ("p2p0: removal not verified", "t_p2p0_del_failure_reported", [
        ("soloist-svc.sh", 'if ipv4ll "$P2P_IF" | grep -qxF "$a"; then', "if false; then"),
    ]),
    ("config: hard-coded wlan0 and name", "t_config_is_used", [
        ("soloist-svc.sh", 'ip -4 addr show "$WLAN_IF"', "ip -4 addr show wlan0"),
        ("run-soloist.sh", '-n "$DEVICE_NAME"', '-n "Станция Лайт"'),
    ]),
    ("cp15: always back to 1", "t_cp15_restored", [
        ("soloist-svc.sh", '{ echo "$v" > "$CP15_FILE"; } 2>/dev/null', '{ echo 1 > "$CP15_FILE"; } 2>/dev/null'),
    ]),
    ("voice: pipeline in foreground", "t_stop_leaves_nothing", [
        ("spotify-voice.sh", 'do act "$a"; done &\nwait $!', 'do act "$a"; done'),
    ]),
    ("voice: no JSON escapes", "t_voice_json_escape", [
        ("spotify-voice.sh", 'if (c == "\\\\") {', "if (0) {"),
    ]),
    ("voice: unknown phrase -> play", "t_voice_unknown_ignored", [
        ("spotify-voice.sh", 'return "unknown"', 'return "play"'),
    ]),
    ("voice: only the last request kept", "t_voice_interleaved", [
        ("spotify-voice.sh", "        txt[id] = t\n", "        for (k in txt) delete txt[k]\n        txt[id] = t\n"),
    ]),
    ("voice: log without rotation", "t_voice_log_rotated", [
        ("spotify-voice.sh", 'log() { log_to "$VLOG" "$@"; }', 'log() { echo "$(date -u \'+%F %T\') $*" >> "$VLOG"; }'),
    ]),
    ("install: no rollback when the init script cannot be written", "t_install_remount_fails_rolls_back", [
        ("install.sh", '    put_init "$GEN" || rollback\n', '    put_init "$GEN"\n'),
    ]),
    ("install: login data not carried over", "t_install_upgrade_keeps_login", [
        ("install.sh", '    cp -a "$TARGET/data" "$STAGE/data" || { say "could not copy data/"; rollback; }\n', '    :\n'),
    ]),
    ("install: failed trial run ignored", "t_install_broken_kit_changes_nothing", [
        ("install.sh", '    die "soloist does not start from the kit: $v"\n', '    true\n'),
    ]),
    ("cp15: missing knob treated as fine", "t_cp15_missing_refuses", [
        ("soloist-svc.sh", '[ -r "$CP15_FILE" ] || { log "no $CP15_FILE"; return 1; }', '[ -r "$CP15_FILE" ] || return 0'),
    ]),
    ("cp15: saved value dropped when restore fails", "t_cp15_restore_failure_kept", [
        ("soloist-svc.sh", '    if [ "$(cat "$CP15_FILE" 2>/dev/null)" = "$v" ]; then', '    if :; then'),
    ]),
    ("gate: key not removed from the log", "t_gate_redacts_key", [
        ("audio-gate.sh", '[ -n "$KEY" ] && line="[line with the API key removed]"', ':'),
    ]),
    ("install: die instead of rollback after the stop", "t_install_stage_move_fails_rolls_back", [
        ("install.sh", 'mv "$STAGE" "$TARGET" || { say "could not move the kit in place"; rollback; }',
         'mv "$STAGE" "$TARGET" || die "could not move the kit in place"'),
    ]),
    ("install: no lock", "t_install_parallel_refused", [
        ("install.sh", 'mkdir "$LOCK" 2>/dev/null || die "another install.sh is running (or remove a stale $LOCK)"', ':'),
    ]),
    ("install: read-only restore not checked", "t_install_ro_restore_fails_reported", [
        ("install.sh", '    root_is_ro && return 0\n    say "rootfs is still read-write"\n    return 1', '    return 0'),
    ]),
    ("volume: Soloist starts at its own default", "t_volume_initial_from_alice", [
        ("run-soloist.sh", 'if [ "$VOLUME_SYNC" = 1 ] && v=$(alice_volume); then INITIAL="-i $v"; fi', ':'),
    ]),
    ("volume: Alice's level passed unscaled", "t_volume_follows_alice", [
        ("lib.sh", 'echo $(( v * 100 / ALICE_VOLUME_MAX ))', 'echo "$v"'),
    ]),
    ("volume: garbage not rejected", "t_volume_garbage_ignored", [
        ("lib.sh", "    case \"$v\" in ''|*[!0-9]*) return 1 ;; esac\n", "    [ -n \"$v\" ] || return 1\n"),
    ]),
    # Not a mutant: "dead aplay not reaped" (Codex) does not reproduce - busybox
    # ash 1.35 collects finished background jobs itself; t_gate_reaps_aplay stays
    # green without reap_aplay and is kept only as a regression guard.
]

bad = 0
for title, test, edits in M:
    d = tempfile.mkdtemp(prefix="mut-")
    shutil.copytree(DEV, d, dirs_exist_ok=True)
    for f, old, new in edits:
        p = os.path.join(d, f)
        s = open(p, encoding="utf-8").read()
        if old not in s:
            sys.exit(f"mutation '{title}': text not found in {f}: {old!r}")
        open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
    r = subprocess.run(["sh", os.path.join(HERE, "run.sh"), d, test], capture_output=True, text=True)
    red = r.returncode != 0
    fails = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("FAIL")]
    print(("RED  " if red else "GREEN") + f" {test:32} without fix '{title}': {'; '.join(fails)}")
    bad += not red
    shutil.rmtree(d)
print("all mutants caught" if not bad else f"{bad} mutant(s) NOT caught")
sys.exit(1 if bad else 0)
