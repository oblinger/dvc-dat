import json
import os
from typing import Dict, Any


_DAT_FILE = ".datconfig"
_DAT_FOLDER_KEY = "dat_data_folder"
_DO_FOLDER_KEY = "do_folder"
_MOUNTS_KEY = "mounts"


class DatConfig(object):
    """Configuration info for the 'dat' module loaded from the .datconfig file.

    .datconfig
        The do module search CWD and all its parent folders for the '.datconfig' file.
        If it is found, it expects a JSON object with a 'do_folder' key that indicates
        the path (relative to the .datconfig file itself) of the "do folder"
    """
    config: Dict[str, Any]
    do_folder: str
    dat_folder: str

    def __init__(self, folder=None):
        self.folder = folder or os.getcwd()
        while True:
            if os.path.exists(config := os.path.join(self.folder, _DAT_FILE)):
                try:
                    with open(config, 'r') as f:
                        self.config = json.load(f)
                except json.JSONDecodeError as e:
                    raise Exception(f"Error loading .datconfig: {e}")
                break
            if self.folder == '/':
                self.folder = os.getcwd()
                break
            self.folder = os.path.dirname(self.folder)

        self.do_folder = self._lookup_path(self.folder, _DO_FOLDER_KEY)
        self.dat_folder = self._lookup_path(self.folder, _DAT_FOLDER_KEY, "dat_data")
        # self.config = {}
        # ### dvc_dat.dat.data_folder = self.dat_folder
        # print(F"# DO_FLDR = {self.do_folder}\n# DAT_DATA = {self.dat_folder}")
        # assert self.do_folder
        assert self.dat_folder

    def _lookup_path(self, folder_path, key, default=None) -> str:
        suffix = self.config[key] if key in self.config else default
        if suffix:
            path = os.path.join(folder_path, suffix)
            os.makedirs(path, exist_ok=True)
        else:
            path = None  # os.path.join(os.getcwd(), default)
        return path


dat_config = DatConfig()

