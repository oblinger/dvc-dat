import json
import os
import weakref
from typing import Dict, Any, Union, List

import yaml

_DAT_CONFIG_JSON = ".datconfig.json"
_DAT_CONFIG_YAML = ".datconfig.yaml"
_DAT_FOLDER = "sync_folder"
_DAT_FOLDERS = "dat_folders"
_DAT_MOUNT_COMMANDS = "mount_commands"
_DEFAULT_DAT_FOLDER = "dat_data"


class DatConfig(object):
    """Configuration info for the 'dat' module loaded from the .datconfig.json.json file.

    .datconfig.json.json
        The do module search CWD and all its parent folders for the '.datconfig.json.json' file.
        If it is found, it expects a JSON object with a 'do_folder' key that indicates
        the path (relative to the .datconfig.json.json file itself) of the "do folder"
    """
    config: Dict[str, Any] = {}
    sync_folder: str
    sync_folders: List[str]   # Note: also includes the dat_folder
    dat_cache: Dict[str, Any] = weakref.WeakValueDictionary()  # Used in Dat.load

    DAT_ADDS_LIST = ".dat_adds.txt"  # List of Dat names to be updated in DVC

    def __init__(self, folder=None):
        self.folder = folder or os.getcwd()
        while True:
            if os.path.exists(config := os.path.join(self.folder, _DAT_CONFIG_JSON)):
                try:
                    with open(config, 'r') as f:
                        self.config = json.load(f)
                except json.JSONDecodeError as e:
                    raise Exception(f"Error loading {_DAT_CONFIG_JSON}: {e}")
                break
            if os.path.exists(config := os.path.join(self.folder, _DAT_CONFIG_YAML)):
                try:
                    with open(config, 'r') as f:
                        self.config = yaml.safe_load(f)
                except yaml.YAMLError as e:
                    raise Exception(f"Error loading {_DAT_CONFIG_YAML}: {e}")
                break
            if self.folder == '/':
                self.folder = os.getcwd()
                break
            self.folder = os.path.dirname(self.folder)

        self.sync_folder = self._lookup_path(self.folder, _DAT_FOLDER, None)
        if not self.sync_folder:
            print(f"Warning: No {_DAT_CONFIG_JSON} found or no \"{_DAT_FOLDER}\" specified.")
            self.sync_folder = os.path.join(self.folder, _DEFAULT_DAT_FOLDER)
        dirs = self.config.get(_DAT_FOLDERS)
        dirs = ([self.sync_folder] + dirs) if dirs else [self.sync_folder]
        self.sync_folders = [os.path.join(self.folder, f) for f in dirs]
        assert self.sync_folder
        assert len(self.sync_folders) > 0

    def _lookup_path(self, folder_path: str, key, default=None) -> Union[str, None]:
        suffix = self.config[key] if key in self.config else default
        if suffix:
            path = os.path.join(folder_path, suffix)
            os.makedirs(path, exist_ok=True)
        else:
            path = None  # os.path.join(os.getcwd(), default)
        return path


dat_config = DatConfig()
