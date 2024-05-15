import os

from dvc_dat import Dat, do, DatContainer

hello_mspipe = {
    "main": {
        "class": "DatContainer",
        "do": "hello_mspipe.pipe_run"
    },
    "common": {
        "main": {
            "base": "hello_std_args_ex",
            "do": "hello_mspipe.mcproc_pass",
        }
    },
    "stages": {
        "preprocessing": {
            "main": {
                "do": "hello_msproc.mcproc_pass",
            }
        }
    }
}


def msproc_build_and_run(dc: DatContainer):
    path: str = dc.get_path()
    common_template = Dat.get(dc, "common")
    for stage_name, stage_template in Dat.get(dc, "stages").items():
        subpath: str = os.path.join(path, stage_name)
        subspec = do.merge_configs(stage_template, common_template)
        Dat(path=subpath, spec=subspec)
    msproc_run(dc)


def msproc_run(dc: DatContainer):
    for stage in dc.get_dat_paths():
        do(stage)
    dc.save()


def mcproc_pass(dat: Dat):
    """Fake MCPROC pass.

    Each output list specified a path to write to, and a list of constructor cmds:
      $$ xxxx     -- this will insert a line with 'xxxx' into the output
      >> xxxx     -- this will insert the contents of the file xxxx into the output

    Returns a string describing how many output files were built by this fake 'pass'
    """
    def build_line(template):
        if template.startswith("$$"):
            return template[2:]
        elif template.startswith(">>"):
            path = os.path.join(dat.get_path(), template[2:])
            with open(path) as f:
                return f.read()
    name = Dat.get(dat, "main.name")
    outputs = Dat.get(dat, "mcproc.outputs")
    for output in outputs:
        path = os.path.join(dat.get_path(), output[0])
        parts = [build_line(part) for part in output[1:]]
        with open(path, 'w') as f:
            f.write('\n'.join(parts))
    return f"Produced {len(outputs)} for run {dat.get_path_name()!r}"
