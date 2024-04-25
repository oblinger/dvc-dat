import json
import os
from typing import Dict, Any


_DAT_FILE = ".datconfig"
_INST_FOLDER_KEY = "inst_data_folder"
_DO_FOLDER_KEY = "do_folder"


class DatConfig(object):
    """Configuration info for the 'dat' module loaded from the .datconfig file.

    .datconfig
        The do module search CWD and all its parent folders for the '.datconfig' file.
        If it is found, it expects a JSON object with a 'do_folder' key that indicates
        the path (relative to the .datconfig file itself) of the "do folder"
    """
    config: Dict[str, Any]
    do_folder: str
    inst_folder: str

    def _lookup_path(self, folder_path, key, default):
        if key in self.config:
            path = os.path.join(folder_path, self.config[key])
        else:
            path = os.path.join(os.getcwd(), default)
        os.makedirs(path, exist_ok=True)
        return path

    def __init__(self, folder=None):
        self.config = {}
        folder = folder or os.getcwd()
        while True:
            if os.path.exists(config := os.path.join(folder, _DAT_FILE)):
                try:
                    with open(config, 'r') as f:
                        self.config = json.load(f)
                except json.JSONDecodeError as e:
                    raise Exception(f"Error loading .datconfig: {e}")
                break
            if folder == '/':
                folder = os.getcwd()
                break
            folder = os.path.dirname(folder)
        self.do_folder = self._lookup_path(folder, _DO_FOLDER_KEY, "do")
        self.inst_folder = self._lookup_path(folder, _INST_FOLDER_KEY, "inst_data")
        # ### ml_dat.inst.data_folder = self.inst_folder
        # print(F"# DO_FLDR = {self.do_folder}\n# INST_DATA = {self.inst_folder}")
        assert self.do_folder
        assert self.inst_folder


dat_config = DatConfig()

