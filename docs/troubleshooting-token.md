## Troubleshooting token detection

If `sie` reports "Token: absent" but you believe the env var is set, run:

```sh
sie -d   # or: sie --debug-env
```

This prints the status of each candidate env var (`SONAR_API_KEY`, `SONAR_TOKEN`): not set / set but empty / set with N chars.

### Common causes of "absent despite being set"

#### 1. Env var not exported
In fish, `set -gx` (not `set -g`) is required to export to subprocesses. Verify with:

```fish
set -q -x SONAR_API_KEY   # exits 0 if set + exported
echo $SONAR_API_KEY | wc -c   # prints 0 if empty, N+1 if set with N chars
```

In bash/zsh, `export VAR=...` (not just `VAR=...`) is required.

#### 2. `kwallet-query` returned empty
If KWallet was locked at shell-startup time, `kwallet-query` fails silently and returns an empty string. The `set -gx` line runs at shell startup; if KWallet isn't unlocked yet, the var is set to `""`.

**Fix**: re-run the `set -gx` line after unlocking KWallet, or restart the shell. For persistent fix, ensure KWallet auto-unlocks on login (KDE Wallet settings → "When the wallet is opened, automatically unlock all wallets" or PAM integration via `kwallet-pam`).

#### 3. `sie` invoked from a non-shell context
Desktop launchers, cron jobs, and non-login shells may not inherit the fish universal var. Run `sie` from a fish terminal directly.

#### 4. Universal var not yet loaded
Fish universal vars (`set -U`) are persisted in `~/.config/fish/fish_variables` and loaded into new sessions. If you set the var in one session and `sie` is running in another, the other session may need a restart.

### The `0` vs `unset` ambiguity

Fish's `set -q -x SONAR_API_KEY` exits 0 (var is set+exported) and `string length $SONAR_API_KEY` prints `0` — but `0` is easy to miss in the output. `sie -d` distinguishes the three cases explicitly: not-set / set-but-empty / set-with-N-chars. This is why the `--debug-env` flag exists.
