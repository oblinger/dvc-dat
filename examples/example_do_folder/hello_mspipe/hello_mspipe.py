import os
from dvc_dat import Dat, do, DatContainer

"""
HELLO-MSPIPE - Hello-world example of a configurable multi-stage mcproc pipeline.

The real multi-stage pipe might can be patterned from this example with 
"fake_mcproc_pass" replaced with code that actually runs a mcproc pass.
"""


# This is the "master template" that all multi-stage pipelines will be based on.
# It specifies that all stages will use "fake_mcproc_pass" by default,
# and constructs its output folders by overwriting "mspipe" in the CWD
# (specific multistage pipes will usually over-ride this to direct output elsewhere).
hello_mspipe = {
    "main": {                          # Section controls execution of whole pipeline
        "kind": "Mspipe",              # "subtype" common to all multi-stage runs
        "class": "DatContainer",       # The python class for a multi-stage runs
        "do": "hello_mspipe.mspipe_build_and_run",   # Actually runs the pipeline
    },
    "common": {
        "main": {
            "kind": "Mcproc",                  # Default "subtype" for all mcproc runs
            "base": "hello_std_args_ex",       # Default parameters for an mcproc run
            "do": "hello_mspipe.fake_mcproc_runner",  # Runs one mcproc stage
        }
    },
    "stages": {}                         # Section defines stages of the pipeline
}


# NOTE: We split the building and running of these DATS; using DVC and MLFLOW this will
# enable us to construct and DVC cache many runs and then execute them across
# a distributed farm of cloud instances.
def mspipe_build_and_run(dc: DatContainer):
    mspipe_build(dc)
    msproc_run(dc)

def mspipe_build(dc: DatContainer):
    """Builds the sub-dats representing each stage."""
    path: str = dc.get_path()
    common_template = Dat.get(dc, "common")
    for stage_name, stage_template in Dat.get(dc, "stages").items():
        subpath: str = os.path.join(path, stage_name)
        subspec = do.merge_configs(stage_template, common_template)
        Dat.create(path=subpath, spec=subspec)


def msproc_run(dc: DatContainer):
    """Sequentially runs each stage in the pipeline."""
    for stage in dc.get_dat_paths():
        do(stage)
    dc.save()


def fake_mcproc_runner(dat: Dat):
    """Fake MCPROC stage runner.

    These stages construct specified output files by concatenating
    specified input files interspersed with specified constant strings.

    Each output template begins with a string containing the path to write to
    This is followed by a sequence of instructions:
      >> xxxx     -- indicates string constant 'xxxx' should be appeneded to the output
      << xxxx     -- indicates the contents of the file xxxx should be added to output

    Returns a string describing how many output files were built by this fake 'pass'
    """
    def build_line(template):
        if template.startswith(">>"):
            return template[2:]
        elif template.startswith("<<"):
            path = os.path.join(dat.get_path(), template[2:])
            with open(path) as f:
                return f.read()
    name = Dat.get(dat, "main.name")
    outputs = Dat.get(dat, "outputs")
    for path_spec, output_spec in outputs.items():
        path = os.path.join(dat.get_path(), path_spec)
        parts = [build_line(part) for part in output_spec]
        with open(path, 'w') as f:
            f.write('\n'.join(parts))
    return f"Produced {len(outputs)} for run {dat.get_path_name()!r}"
