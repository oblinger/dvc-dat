
"""
IO - The I/O module is responsible for packaging and unpackaging inst data.


"""

import zipfile
import os
from abc import ABC, abstractmethod
import boto3

from inst import Inst


class IO(ABC):
    """IO - The I/O class manages the pulling and pushing data from cloud storage.


    - Each version of an Inst has a DOTTED_NAME and a YYYY-MM-DD-NNN version string.
    - Its URI is formed as: "URI_BASE/SLASHED_NAME/Inst-YYYY-MM-DD-NNN.zip"
    - Its local folder is formed as: "LOCAL_BASE/SLASHED_NAME/"


    """

    def __init__(self, cloud: str):
        self.cloud = cloud
        self.s3_client = boto3.client('s3')

    @abstractmethod
    def load_inst(self, name: str) -> Inst:
        """Load an Inst object from cloud storage given its name."""

        pass

    @abstractmethod
    def load_folder(self, uri: str, into: str):
        """Load a folder from the cloud storage."""
        pass

    @abstractmethod
    def save_folder(self, uri: str, from_: str):
        """Save a folder to the cloud storage."""
        pass

    @abstractmethod
    def load_file(self, uri: str, into: str):
        """Load data from the cloud storage."""
        pass

    @abstractmethod
    def save(self, uri: str, from_: str):
        """Save data to the cloud storage."""
        pass



class S3IO(IO):
    """S3IO - The S3 I/O class manages pulling and pushing data from S3 cloud storage."""
    def __init__(self, cloud: str):
        super().__init__(cloud)
        self.s3_client = boto3.client('s3')

    def load_folder(self, uri: str, into: str):
        """Load a folder from the cloud storage."""
        bucket_name, key = uri.replace("s3://", "").split("/", 1)
        zip_path = os.path.join(into, 'temp.zip')
        self.s3_client.download_file(bucket_name, key, zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(into)
        os.remove(zip_path)

    def save_folder(self, uri: str, from_: str):
        """Save a folder to the cloud storage."""
        zip_path = os.path.join(from_, 'temp.zip')
        with zipfile.ZipFile(zip_path, 'w') as zip_ref:
            for foldername, subfolders, filenames in os.walk(from_):
                for filename in filenames:
                    zip_ref.write(os.path.join(foldername, filename),
                                  os.path.relpath(os.path.join(foldername, filename),
                                                  from_),
                                  compress_type = zipfile.ZIP_DEFLATED)
        bucket_name, key = uri.replace("s3://", "").split("/", 1)
        self.s3_client.upload_file(zip_path, bucket_name, key)
        os.remove(zip_path)

    def load(self, uri: str, into: str):
        """Load a single file from an S3 uri into a local file using the boto3 library."""
        bucket_name, key = uri.replace("s3://", "").split("/", 1)
        self.s3_client.download_file(bucket_name, key, into)

    def save(self, uri: str, from_: str):
        """Save data to the cloud storage."""
        bucket_name, key = uri.replace("s3://", "").split("/", 1)
        self.s3_client.upload_file(from_, bucket_name, key)