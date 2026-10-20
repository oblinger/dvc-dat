# ledger.env

The environment a function runs in is found, never declared: which
repositories the process is running, at which commit, whether their
trees are clean, which `uv.lock`, which platform. Discovery runs git
over the folder of every module the process has imported, skipping the
standard library, `site-packages` and the dvc-dat checkout itself (the
ledger's own repo is infrastructure, like `site-packages`). The commit
is read on every call, never cached, so a notebook that commits
mid-session is seen. Part of the
[architecture](../../DAT%20Architecture.md).

## Public surface

- `Code(version, commit, dirty=False, path=None)`: one repo as the
  environment has it; `version` is always `None` from discovery;
  `dirty` means tracked files are modified (untracked ignored, and any
  path `.gitattributes` marks `dat-noncode`, as `code_of`, 6.2.1); `path`
  the checkout root a mount's `db/root` resolves under.
- `Env(code, lock, platform, mounts=None)`: `code` maps repo name to
  `Code`; `lock` is `sha256:<hex>` of the `uv.lock` found beside the
  venv (`sys.prefix`'s parent) or in the working directory, else
  `<none>`; `platform` is `<sys.platform>-<machine>-py<X.Y>`.
- `discover() -> Env`: the default provider.
- `current_env() -> Env`: the installed provider's answer, else
  `discover()`.
- `set_env_provider(provider | None) -> old`: the test seam; replaces
  discovery, `None` restores it. A sandbox worker uses it to adopt the
  parent's view.
- `repo_name(top) -> str`: the checkout's `pyproject.toml`
  `[project].name`, normalised (`dvc_dat` → `dvc-dat`), else the folder
  name.
- `repo_of(env, path) -> str | None`: the deepest reported checkout
  holding `path`.
- `code_at(top) -> Code`, `lock_hash()`, `platform_tag()`, `SELF =
  "dvc-dat"`.

## Invariants

- No repo named `dvc-dat` is ever reported, and no module under the
  installed `dvc_dat` package counts; a demo folder inside the dvc-dat
  checkout is reported only when it is a checkout of its own.
- Only imported modules count: a repo the process has not imported
  from is not in `Env.code`, so `bump(t, "code/<repo>")` needs one of
  its modules imported.
- `git rev-parse --show-toplevel` answers are cached per folder; HEAD
  and dirtiness are not.

## Left to other modules

What the environment means is decided elsewhere: the `code/<repo>`
token in [txn](txn.md), the code checks in [fn](fn.md) and
[sandbox](sandbox.md), the commit `bump` writes in
[helpers](helpers.md), the hit test in [trace](trace.md).
