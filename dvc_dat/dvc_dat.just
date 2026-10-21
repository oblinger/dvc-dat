# dvc-dat's recipes, for a project's justfile to import. `just run TARGET`
# is the one way to run; `x TARGET` (bin/x) is `just run TARGET`.
#
#     import 'dvc_dat.just'    # a link to the installed dvc_dat/dvc_dat.just
#
# `run` walks up from the working directory to the nearest .datconfig.yaml,
# picks a command ($DAT_RUN, else the config's `run:` key, else
# `.venv/bin/python -m dvc_dat` beside the config, else
# `python3 -m dvc_dat`), and execs it with the arguments appended and the
# working directory unchanged. The child sees DAT_CLI_CONFIG, the config
# file: a program's own main tests it to know it was launched by `run`, and
# `dat.cli_main()` reads the config from it. The config folder is the
# import root (PYTHONPATH). Exit 3 when no .datconfig.yaml is above the
# working directory.

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
    export DAT_CLI_CONFIG
    cfg_run=$(sed -n 's/^run:[[:space:]]*//p' "$dir/.datconfig.yaml" | head -n 1 |
        sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")
    if [ -n "$DAT_RUN" ]; then
        run=$DAT_RUN
    elif [ -n "$cfg_run" ]; then
        run=$cfg_run
    elif [ -x "$dir/.venv/bin/python" ]; then
        run="$dir/.venv/bin/python -m dvc_dat"
    else
        run="python3 -m dvc_dat"
    fi
    eval "set -- $run \"\$@\""
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
