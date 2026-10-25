# Code conventions and runtime plumbing

Type: grilling
Status: open
Blocked by: —

## Question

Which code conventions should M0 lock in? Decide:
- **Package layout:** under `src/phy/`.
- **CLI framework:** Typer?
- **Database access:** raw `sqlite3` or a thin layer, and how the schema is migrated.
- **Config:** loading and validating `config.toml` and `questions.yaml`.
- **Logging.**
- **Testing:** recorded OAI-PMH and API fixtures, no live calls by default, and one opt-in live smoke test.
- **Credentials:** how the API key reaches the launchd job. QUICK_START currently says `~/.zshenv`, which is wrong because launchd doesn't read shell profiles. The options are an `ant auth login` profile, the plist's `EnvironmentVariables`, a gitignored `.env`, or the macOS Keychain.
- **Locking:** the lock-file mechanics for `phy daily` and for the arXiv rate limiter.
