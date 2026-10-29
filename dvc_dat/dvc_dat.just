# dvc-dat's recipes, for a project's justfile to import. `just run TARGET`
# is the one way to run; `x TARGET` (bin/x) is `just run TARGET`. Below
# `mounts`, the ledger verbs: values, value, history, why, set, index, bump.
#
#     import 'dvc_dat.just'    # a link to the installed dvc_dat/dvc_dat.just
#
# `run` walks up from the working directory to the nearest .datconfig.yaml,
# picks a command ($DAT_RUN, else the config's `run:` key, else
# `.venv/bin/python -m dvc_dat` beside the config, else
# `python3 -m dvc_dat`), and execs it with the arguments appended and the
# working directory unchanged. The child sees DAT_CLI_CONFIG, the config
# file: a program's own main tests it to know it was launched by `run`, and
# `dat.cli_main()` reads the config from it; and DAT_JUSTFILE, the justfile,
# whose `import? '.dat/targets.just'` asks for the generated commands. The
# config folder is the import root (PYTHONPATH). Exit 3 when no
# .datconfig.yaml is above the working directory.
#
# With a `ledger:` line or a `ledgers:` section, `run` runs TARGET through the active ledger:
# found if computed before from the same inputs by the same code, else run
# and sealed; `alias=NAME` names the result. Without one it records nothing.

# run TARGET [ARG ...] [KEY=VALUE ...]: a mounted name, a dotted function, a spec
[no-cd]
[positional-arguments]
run *args:
    #!/bin/sh
    dir=$PWD
    while [ ! -f "$dir/.datconfig.yaml" ]; do
        [ "$dir" = "/" ] && {
            echo "run: no .datconfig.yaml in $PWD or any parent" >&2
            exit 3
        }
        dir=$(dirname "$dir")
    done
    DAT_CLI_CONFIG=$dir/.datconfig.yaml
    DAT_JUSTFILE="{{justfile()}}"
    export DAT_CLI_CONFIG DAT_JUSTFILE
    cfg_run=$(sed -n 's/^run:[[:space:]]*//p' "$dir/.datconfig.yaml" | head -n 1 |
        sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")
    if [ -n "$DAT_RUN" ]; then
        eval "set -- $DAT_RUN \"\$@\""
    elif [ -n "$cfg_run" ]; then
        eval "set -- $cfg_run \"\$@\""
    elif [ -x "$dir/.venv/bin/python" ]; then
        set -- "$dir/.venv/bin/python" -m dvc_dat "$@"     # one word: a project path may hold a space
    else
        set -- python3 -m dvc_dat "$@"
    fi
    case $1 in
        /*) ;;
        */*) first=$dir/$1; shift; set -- "$first" "$@" ;;
    esac
    case $1 in
        */*)
            [ -x "$1" ] || {
                echo "run: $1 is not an executable" >&2
                exit 1
            } ;;
        *)
            command -v "$1" >/dev/null 2>&1 || {
                echo "run: $1 is not on PATH" >&2
                exit 1
            } ;;
    esac
    PYTHONPATH=$dir${PYTHONPATH:+:$PYTHONPATH}
    export PYTHONPATH
    exec "$@"

# mounts [PREFIX]: the mounted names, with what each loads to
[no-cd]
[positional-arguments]
mounts *args:
    @"{{just_executable()}}" -f "{{justfile()}}" run --list "$@"

# The ledger verbs (SVP 1465): each is `python -m dvc_dat.ledger.recipes VERB`,
# one ledger call (`Ledger()`, the active ledger: $DAT_LEDGER, else the nearest
# .datconfig.yaml's `ledgers:` default or `ledger:`), run from the working directory. The interpreter is
# $DAT_PYTHON, else .venv/bin/python beside the justfile, else python3. A
# project that keeps its own recipe of one of these names calls the module
# instead. Keys and preds: `k=v`, v JSON, else the text as typed.
_dat_python := env("DAT_PYTHON", if path_exists(justfile_directory() / ".venv/bin/python") == "true" { justfile_directory() / ".venv/bin/python" } else { "python3" })

# the values matching k=v preds (kind=<short class name> narrows)
[no-cd]
[positional-arguments]
values *args:
    @"{{_dat_python}}" -m dvc_dat.ledger.recipes values "$@"

# exactly one value matching the preds
[no-cd]
[positional-arguments]
value *args:
    @"{{_dat_python}}" -m dvc_dat.ledger.recipes value "$@"

# every row a subject has held, with each revision's db/by
[no-cd]
[positional-arguments]
history subject:
    @"{{_dat_python}}" -m dvc_dat.ledger.recipes history "$@"

# a value's dependencies, whether they hold at the head, and what moved since the alias's last target
[no-cd]
[positional-arguments]
why name *args:
    @"{{_dat_python}}" -m dvc_dat.ledger.recipes why "$@"

# rows on a subject: k=v a fact, alias=TARGET the name's value (a hash prefix is expanded)
[no-cd]
[positional-arguments]
set subject *args:
    @"{{_dat_python}}" -m dvc_dat.ledger.recipes set "$@"

# declare a pred indexed
[no-cd]
[positional-arguments]
index pred:
    @"{{_dat_python}}" -m dvc_dat.ledger.recipes index "$@"

# bump a version: <module> edits its __version__ in the source; db is the ledger's release (a/b: a ledger clock); minor and major ask for yes
[no-cd]
[positional-arguments]
bump name part="patch":
    @"{{_dat_python}}" -m dvc_dat.ledger.recipes bump "$@"
