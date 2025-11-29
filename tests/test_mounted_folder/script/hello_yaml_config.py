# Example of using YAML string format for configs embedded in Python files.
# The "yaml" prefix tells dvc-dat to parse the string as YAML.

__main__ = """yaml
dat:
  base: hello_config
  do: configurable_salutation
name: YAML Greeter
lucky_number: 888
emphasis: true
"""
