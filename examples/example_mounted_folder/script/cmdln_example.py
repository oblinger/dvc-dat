import yaml


usage = """
Do cmd "cmdln_example" is a simple stub that shows how to create a do command.

  do cmdln_example KEYS    # simple example showing
    --show-args            # shows passed args
    --show-spec            # this prints the spec used
    
"""


__main__ = {
  "dat": {"do": "cmdln_example.run"},
  "example": {
    "arg1": 111,
    "arg2": 222
  }
}


def run(*args, **kwargs):
    if "show_args" in kwargs:
        print(F" ARGS={args}  KWARGS={kwargs}")
    if "show_spec" in kwargs:
        print("SPEC:")
        print(yaml.safe_dump(args[0], default_flow_style=False, indent=2))
