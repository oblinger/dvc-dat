
from dvc_dat.dat import Dat

"""
This module is a stub that eventually may be used to provide auto uploading and 
downloading of Dats to/from the cloud.
"""


class DatIO:
    """Handle cloud IO for the Dat class."""

    @staticmethod
    def load(name: str) -> Dat:
        """Load a Dat object from the cache or create a new one"""
        return Dat.manager.load(name)

    @staticmethod
    def save(dat: Dat):
        """Save the Dat object to the cache"""
        dat.save()
