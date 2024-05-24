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

1. **Dat class** -- named, DVC-version, folder with associated meta data and 
    action-code bindings.

2. **do function** -- maps source-code structures and function into a space of 
   dotted.name.strings for easy reference within text configuration files.

3. **from_isdatance function** -- builds a pandas DataFrame by applying a set of 
   metrics (python code-bindings) over a set of Dats.

4. **to_excel function** -- slices and formats a pandas DataFrame into a collection 
   of Execl documents and sheets for presentation.
   
5. **metrics_matrix function** -- wraps these functions into configurable report 
   generator.


### API OVERVIEW

#### Manipulating dict trees

| Method                                   | Description                 |
|------------------------------------------|-----------------------------|
| Dat.get(Dat/dict, [key1,...]) -> value | Get from tree of dict       |
| Dat.get(Dat/dict, "dotted.key.name")   | Get using dotted.names      |
| Dat.set(dict, [key1, key2, ...], value) | Sets into a tree of dict    |
| Dat.set(dict, "dotted.key.path", value) | Set using dotted names      |
| Dat.gets(Dat/dict, NAMES) -> VALUES    | Get multiple values at once |
| Dat.sets(dict, ASSIGNMENTS)             | Set multiple values at once |


#### Managing data folders

| Method                          | Description                                      |
|---------------------------------|--------------------------------------------------|
| Dat.create(path=, spec=) -> Dat | Create a new Dat with a given spec and path.     |
| Dat.create_from_template(...)   | Creates after performing spec expansion          |
| Dat.load(NAME) -> Dat           | Load a Dat by name                               |
| .get_spec() -> Dict             | Get the spec of the Dat.                         |
| .get_path() -> Path             | Get the path of the Dat.                         |
| .get_path_name() -> str         | Get the name of the Dat (relative to repo)       |
| .get_path_tail() -> str         | Get last part of path (used as Dat's short name) |
| .save() -> None                 | Save the Dat to the filesystem.                  |
| .delete() -> None               | Delete the Dat from the filesystem.              |
| .copy(PATH) -> Dat              | Copy the Dat to a new location.                  |
| .move(PATH) -> Dat              | Move the Dat to a new location.                  |


#### Loading objects from source-code

| Method                           | Description                                  |
|----------------------------------|----------------------------------------------|
| do.load(NAME) -> Any             | Loads Python source-code obj by dotted.name  |
| do.mount(module=, at=)           | Registers a python module by name            |
| do.mount(file=, at=)             | Registers a .json, .yaml, or .py file        |
| do.mount(value=, at=)            | Registers structured value in do space       |
| do.mount(files_shallowly=, at=)  | Registers ALL .json, .yaml, or .py shallowly | 
| do.get_module(BASE) -> MODULE    | Load a python module from a string spec      |
| do(NAME) -> Any                  | Load a python object from a string spec.     |
| do.set_do_folder(PATH) -> None   | Set the folder to load python objects from.  |
| do.get_base_object(BASE) -> Any  | Get the base object based on it name.        |
| do.merge_configs(BASE, override) | Merge a config with an override.             |
| do.expand_spec(SPEC) -> SPEC     | Recursively merges spec with base spec.      |


#### DAT_TOOLS - Data Frame manipulation

|                                                  |                            |
|--------------------------------------------------|----------------------------|
| dt.from_isdatance([Dat, ...], [point_fn, ...]) -> DF | Applies point_fns to dats |
| dt.to_excel(DF, PATH) -> None                    | Save a DF to an excel file |

    

