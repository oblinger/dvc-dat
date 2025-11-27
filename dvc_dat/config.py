import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Self

import yaml
from pydantic import BaseModel, Field, model_validator

from dvc_dat import utils

logger = logging.getLogger(__name__)

DATA_CONFIG_FILE = ".dataconfig.yaml"
DATA_CONFIG_OVERRIDE_FILE = ".dataconfig.override.yaml"


class DataConfig(BaseModel):
    """Container for data-related configuration.

    Attributes
    ----------
    cwd : Cwd used for operations that involve the local filesystem.
    default_remote : Default protocol that will be used for remote operations. Must be
        one of `fsspec.available_protocols()`.
    remote_prefix : Prefix that will be added to remote URIs when object paths are
        relative.
    local_prefix : Prefix that will be added to local URIs when object paths are
        relative. This is the location under which data will be stored by the
        DataManager under normal operation. If provided as a relative path, it will be
        assumed to be relative to `cwd`.

    """

    cwd: str

    default_remote: str = "gs"
    remote_prefix: str = "sv-ai-data/"
    local_prefix: str = "data/"
    extra_local_prefixes: List[str] = Field(default_factory=list)
    dat: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def new(
        cls,
        cwd: Optional[Union[str, Path]] = None,
        config_name: str = DATA_CONFIG_FILE,
        config_override_name: str = DATA_CONFIG_OVERRIDE_FILE,
        override_values: Optional[Dict[str, Any]] = None,
        verbose: bool = False,
    ) -> "DataConfig":
        """Create a DataConfig.

        All values for the DataConfig (except cwd) will be taken from the following
        sources in order of priority:

        1. Environment variables
        2. Values in `override_values`
        3. Configuration override file.
        4. Configuration file.
        5. Default class values.

        If a value for a config option is found on a higher priority source, it will
        shadow all other lower priority values.

        The config file is just a yaml file with a special name defined by
        `config_name`. Upon instantiation, the file named `config_name` will be searched
        in the current directory, and in every directory above that, until it's found.

        Parameters
        ----------
        cwd : Optional[Union[str, Path]]
            The working directory that will be used in the config. If None, the cwd will
            be the path in which the config file is. If that's not found, cwd will be
            Path.cwd().
        config_name : str
            Name of the config file.
        override_values : Dict, optional
            If provided, the config will read values from here.
        verbose : bool
            If True, verbose logging messages will be printed.

        Returns
        -------
        "DataConfig"
            The instantiated config.

        """
        if cwd:
            cwd = str(cwd)
        if override_values is None:
            override_values = {}

        config_path = cls._find_file_up(
            Path.cwd(),
            config_name,
        )
        config_override_path = cls._find_file_up(
            Path.cwd(),
            config_override_name,
        )

        config_values = {}
        if config_path:
            with config_path.open("r") as f:
                config_values = yaml.safe_load(f)
            if verbose:
                logger.debug("%s found and loaded.", config_path)
        elif verbose:
            logger.warning("%s not found. Using defaults.", config_path)

        config_override_values = {}
        if config_override_path:
            with config_override_path.open("r") as f:
                config_override_values = yaml.safe_load(f)
            if verbose:
                logger.debug("%s found and loaded.", config_path)
        elif verbose:
            logger.warning("%s not found. Using defaults.", config_path)

        if not cwd:
            if config_path:
                cwd = str(config_path.parent)
            else:
                cwd = str(Path.cwd())
        logger.debug("Using cwd: %s", cwd)

        environ_values = dict(os.environ)

        final_values: Dict[str, Any] = utils.merge_dicts(
            config_values,
            config_override_values,
            override_values,
            environ_values,
            {"cwd": cwd},
        )

        return cls(**final_values)

    @staticmethod
    def _find_file_up(
        path: Union[str, Path],
        file_name: str,
    ) -> Optional[Path]:
        """Look for a file with name `file_name` in the CWD and its parents."""
        path = Path(path)
        path = path.absolute()

        file: Optional[Path] = None
        prev_path: Optional[Path] = None

        # Path.walk() wasn't introduced until 3.12
        while prev_path != path:
            file = next(path.glob(file_name), None)
            if file:
                break
            prev_path = path
            path = path.parent
        return file

    @model_validator(mode="after")
    def resolve_paths(self) -> Self:
        """Make every path used in the config absolute to avoid ambiguity."""
        self.cwd = os.path.realpath(self.cwd)

        # remote prefixes must always be absolute
        if not os.path.isabs(self.remote_prefix):
            self.remote_prefix = os.path.join("/", self.remote_prefix)
        if not self.remote_prefix.endswith("/"):
            self.remote_prefix += "/"

        # local prefix is relative to CWD or absolute
        if not os.path.isabs(self.local_prefix):
            self.local_prefix = os.path.join(self.cwd, self.local_prefix)
        if not self.local_prefix.endswith("/"):
            self.local_prefix += "/"
        return self

    # FIXME: add this if we want to use fsspec
    # @model_validator(mode="after")
    # def validate_values(self) -> Self:
    #     assert self.default_remote in fsspec.available_protocols(), (
    #         f"Invalid default remote protocol <{self.default_remote}>."
    #     )
    #     return self
