# MK-DAT

DVC-DAT - Thin python wrapper for DVC-based ML-datasets and workflows
- Python bindings for pulling/pushing data folders directly from DVC.
- Git-like work flow for staging then pushing updates to the DVC data-repo.
- Folder declaratively configured via json/yaml to dynamically launched python actions
  (supports ML-Flow experiment and model building workflows)
- Pandas DataFrames and Excel reporting over metrics applied to trees of data folders



## OVERVIEW

ML-DAT provides a simple way to manage data for machine learning projects.
It has one key class and four key functions:

1. **Dat** -- A named, DVC-version, folder with associated metadata and 
    python action bindings.

2. **do** -- Loads source-code structures and function into a space of 
   dotted.name.strings for easy reference within text configuration files.

3. **from_dat** -- builds a pandas DataFrame by applying a set of 
   metrics (python code-bindings) over a set of Dats.

4. **to_excel** -- slices and formats a pandas DataFrame into a collection 
   of Execl documents and sheets for presentation.
   
5. **dat_report** -- wraps these functions into configurable report 
   generator.


### API OVERVIEW

#### Manipulating dict trees

Getters and setters for nested dictionaries.

| Method                                            | Description                 |
|---------------------------------------------------|-----------------------------|
| Dat.get(Dat/dict, [key1,...], [default]) -> value | Get from tree of dict       |
| Dat.get(Dat/dict, "dotted.key.name", [default])   | Get using dotted.names      |
| Dat.set(dict, [key1, key2, ...], value)           | Sets into a tree of dict    |
| Dat.set(dict, "dotted.key.path", value)           | Set using dotted names      |
| Dat.gets(Dat/dict, NAMES) -> VALUES               | Get multiple values at once |
| Dat.sets(dict, ASSIGNMENTS)                       | Set multiple values at once |


Examples:
x = {}
Dat.set(x, "a.b.c", 1)  # x = {'a': {'b': {'c': lambda x: 20}}}
Dat.get(x, "a.b.c")()     # returns 20





#### Managing Dat data folders

| Method                          | Description                                       |
|---------------------------------|---------------------------------------------------|
| Dat.create(path=, spec=) -> Dat | Create a new Dat from path template and spec.     |
| Dat.load(NAME) -> Dat           | Load a Dat by name                                |
| Dat.exists(NAME) -> bool        | Returns True iff named Dat exists                 |
| .get_spec() -> Spec             | Returns the spec Dict tree for this Dat.          |
| .get_results() -> Spec          | Returns the results Dict tree for this Dat.       |
| .get_path() -> Path             | Get the path of the Dat.                          |
| .get_path_name() -> str         | Get the name of the Dat (relative to repo)        |
| .get_path_tail() -> str         | Get last part of path (used as its short name)    |
| .save() -> None                 | Saves Dat's results to the filesystem.            |
| .delete() -> None               | Delete the Dat from the filesystem.               |
| .copy(NAME) -> Dat              | Copy the Dat to a new location.                   |
| .move(NAME) -> Dat              | Move the Dat to a new location.                   |
| ------------------------------- | ------------------------------------------------- |
| DatContainer Methods            | Description                                       |
| .get_dat_paths() -> [str]       | Get the paths of all sub-Dats in the container.   |
| .get_dats() -> [Dat]            | Loads and returns all the Dats in the container.  |

Note: NAME can be a full path, a path relative to the repo root or CWD.

Dat Containers are Dats that recursively contain other Dats.




#### Loading objects from source-code

A DoManager (usually accessed via the 'do' singleton) is used to load python 
source code objects and functions.

| Method                           | Description                                  |
|----------------------------------|----------------------------------------------|
| DoManager()                      | Creates a new do namespace.                  |
| .load(NAME, default=) -> Any     | Loads Python source-code obj by dotted.name  |
| do(NAME, *args, **kwargs) -> Any | Loads the named Python fn and calls it.      |
| do(DAT, *args, **kwargs) -> Any  | Invokes fn at 'dat.do' within the Dat's spec |
| .mount(module=, at=)             | Registers a python module by name            |
| .mount(file=, at=)               | Registers a .json, .yaml, or .py file        |
| .mount(value=, at=)              | Registers structured value in do space       |
| .mount(files_shallowly=, at=)    | Registers ALL .json, .yaml, or .py shallowly | 
| .add_do_folder(PATH) -> None     | Set the folder to load python objects from.  |
| .get_base(BASE) -> Any           | Get the base object based on it name.        |
| .merge_configs(BASE, override)   | Merge a config with an override.             |
| .expand_spec(SPEC) -> SPEC       | Recursively merges spec with base spec.      |
| .dat_from_template(path=,spec=)  | Expands spec and uses it to call Dat.creates |

NAME is a dotted.name.string that refers to a python object or function.




#### DAT_TOOLS - Data Frame manipulation

| Dat Tools Functions                              | Description                     |
|--------------------------------------------------|---------------------------------|
| list([prefix])                                   | Lists defined do cmds w/ prefix |
| dt.from_dat([Dat, ...], [point_fn, ...]) -> DF   | Applies point_fns to dats       |
| dt.to_excel(DF, PATH) -> None                    | Save a DF to an excel file      |
| dt.dat_report(spec, title=, folder=, source=,    | Build Excel report from Dats    |
| ....  metrics=, docs=, sheets=, columns=         |                                 |
| ....  formatted_columns=, verbose=, show=) -> DF |                                 |
| Cube(points=, dats=, point_fns=)                 | Creates a Data Cube from Dats   |


#### .datconfig - Configuration of dvc-dat

Like git, dvc-dat walks up the path from the current working directory looking for 
the '.datconfig.json' file, and uses that file to control behavior. 
Here is an example:

 # .datconfig.json
```json
{
  "sync_folder": "local/sync",
  "mount_commands": [
    {"at": "",     "folder": "other/dat/data"},
    {"at": "",     "folder": "myscript_folder"},
    {"at": "",     "value": {"a_key": "main.py"}},
    {"at": "sub/folder",  "file": "myscripts/a_python.py"}
  ]
}
```

- The "sync_folder" indicates where the DVC sync folder is located, this should be a git-tracked folder where the 
  .dvc control files are stored.
- The "folder" mount command indicates other root folders where Dat objects may be stored.
  These folders are scanned before the sync folder to find local copies of Dats.
- Both the sync folder and these mounted folders are used when looking for do values and functions.
- The "value" mount command allows you to mount a python object directly into the do space.
- The "file" mount command allows you to mount a python module directly into the do space.
  (See the examples section for details.)


