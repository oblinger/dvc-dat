"""
DEPRECATED: Old initialization logic from the main branch.

This file contains the old initialization code that relied on:
- _DAT_MOUNT_COMMANDS constant
- Dat.manager.config as a dict
- Dat.manager.folder attribute
- DoManager with mount_all method

This is preserved for reference during the migration to the new DataConfig-based system.
Once the migration is complete, this file should be deleted.
"""

# OLD __init__.py code:
#
# if not hasattr(main, "NO_DAT_DVC_INIT"):
#     dats = Dat.manager
#     do = Dat.manager.do = DoManager()  # not available during load of do_fn
#
#     from .dat import Dat, DatContainer
#     from . import dat_tools
#
#     cmds = Dat.manager.config.get(_DAT_MOUNT_COMMANDS, [])
#     do.mount_all(cmds, relative_to=Dat.manager.folder)
#     do.mount(module=dat_tools, at="dat_tools")
#     do.mount(module=dat_tools, at="dt")
#     do.mount(value=dat_tools.cmd_list, at="dt.list")
#     do.mount(value=dat_tools.cmd_list, at="dat_tools.list")
#
# The new system uses DataConfig from config.py which:
# - Looks for .dataconfig.yaml instead of .datconfig.yaml
# - Uses a Pydantic model instead of a raw dict
# - Has different attribute names (main_sync_folder vs folder, etc.)
