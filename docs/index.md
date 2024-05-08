# MK-DAT


## OVERVIEW

ML-DAT provides a simple way to manage data for machine learning projects.
It has one key class and four key functions:

1. **Inst class** -- provides a python handle for named data folders that are cached
   and versioned by DVC.

2. **do function** -- maps source-code structures and function into a space of 
   dotted.name.strings for easy reference within text configuration files.

3. **from_inst function** -- builds a pandas DataFrame by applying a set of 
   metrics (python functions) over a set of Insts.

4. **to_excel function** -- slices and formats a pandas DataFrame into a collection 
   of Execl documents and sheets for presentation.
   
5. **metrics_matrix function** -- wraps these functions into configurable report 
   generator.


### API OVERVIEW

#### Manipulating dict trees

| Method                                   | Description                 |
|------------------------------------------|-----------------------------|
| Inst.get(Inst/dict, [key1,...]) -> value | Get from tree of dict       |
| Inst.get(Inst/dict, "dotted.key.name")   | Get using dotted.names      |
| Inst.set(dict, [key1, key2, ...], value) | Sets into a tree of dict    |
| Inst.set(dict, "dotted.key.path", value) | Set using dotted names      |
| Inst.gets(Inst/dict, NAMES) -> VALUES    | Get multiple values at once |
| Inst.sets(dict, ASSIGNMENTS)             | Set multiple values at once |


#### Managing data folders

| Method                   | Description                                   |
|--------------------------|-----------------------------------------------|
| Inst(SPEC, PATH) -> Inst | Create a new Inst with a given spec and path. |
| Inst.load(NAME) -> Inst  | Load an Inst by name                          |
| .spec -> Dict            | Get the spec of the Inst.                     |
| .path -> Path            | Get the path of the Inst.                     |
| .name -> Str             | Get the name of the Inst.                     |
| .save() -> None          | Save the Inst to the filesystem.              |
| .load() -> None          | Load the Inst from the filesystem.            |
| .delete() -> None        | Delete the Inst from the filesystem.          |
| .copy() -> Inst          | Copy the Inst to a new location.              |
| .move() -> Inst          | Move the Inst to a new location.              |


#### Loading objects from source-code

| Method                                | Description                                 |
|---------------------------------------|---------------------------------------------|
| do.load(NAME) -> Any                  | Loads Python source-code obj by dotted.name |
| do.register_module(BASE, SPEC)        | Register a python module by name            |
| do.get_module(BASE) -> MODULE         | Load a python module from a string spec     |
| do.register_value(NAME, VALUE)        | Register a python object by name.           |
| do(NAME) -> Any                       | Load a python object from a string spec.    |
| do.set_do_folder(PATH) -> None        | Set the folder to load python objects from. |
| do.get_base_object(BASE) -> Any       | Get the base object based on it name.       |
| do.merge_configs(BASE, override)      | Merge a config with an override.            |
| do.expand_spec(SPEC) -> SPEC          | Recursively merges spec with base spec.     |


#### DAT_TOOLS - Data Frame manipulation

|                                                  |                            |
|--------------------------------------------------|----------------------------|
| dt.from_inst([Inst, ...], [point_fn, ...]) -> DF | Applies point_fns to insts |
| dt.to_excel(DF, PATH) -> None                    | Save a DF to an excel file |

    

