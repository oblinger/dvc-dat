import json
import os
import weakref
from typing import Dict, Any, Union, List

_DAT_FILE = ".datconfig.json"
_DAT_FOLDER = "dat_data_folder"
_DAT_FOLDERS = "dat_folders"
_DAT_MOUNT_COMMANDS = "mount_commands"


class DatConfig(object):
    """Configuration info for the 'dat' module loaded from the .datconfig.json.json file.

    .datconfig.json.json
        The do module search CWD and all its parent folders for the '.datconfig.json.json' file.
        If it is found, it expects a JSON object with a 'do_folder' key that indicates
        the path (relative to the .datconfig.json.json file itself) of the "do folder"
    """
    config: Dict[str, Any]
    dat_folder: str
    dat_data_folders: List[str]   # Note: also includes the dat_folder
    dat_cache: Dict[str, Any] = weakref.WeakValueDictionary()  # Used in Dat.load

    def __init__(self, folder=None):
        self.folder = folder or os.getcwd()
        while True:
            if os.path.exists(config := os.path.join(self.folder, _DAT_FILE)):
                try:
                    with open(config, 'r') as f:
                        self.config = json.load(f)
                except json.JSONDecodeError as e:
                    raise Exception(f"Error loading .datconfig.json.json: {e}")
                break
            if self.folder == '/':
                self.folder = os.getcwd()
                break
            self.folder = os.path.dirname(self.folder)

        self.dat_folder = self._lookup_path(self.folder, _DAT_FOLDER, "dat_data")
        dirs = self.config.get(_DAT_FOLDERS)
        dirs = ([self.dat_folder] + dirs) if dirs else [self.dat_folder]
        self.dat_data_folders = [os.path.join(self.folder, f) for f in dirs]
        assert self.dat_folder
        assert len(self.dat_data_folders) > 0
        x = 1

    def _lookup_path(self, folder_path: str, key, default=None) -> Union[str, None]:
        suffix = self.config[key] if key in self.config else default
        if suffix:
            path = os.path.join(folder_path, suffix)
            os.makedirs(path, exist_ok=True)
        else:
            path = None  # os.path.join(os.getcwd(), default)
        return path


dat_config = DatConfig()
