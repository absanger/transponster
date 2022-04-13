# -*- coding: utf-8 -*-
#
# Copyright © 2022 Genome Research Ltd. All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# @author Adam Blanchet <ab59@sanger.ac.uk>

"""Useful types"""
from dataclasses import dataclass
from enum import Enum, auto
from threading import Event, Lock
import os
from os import PathLike, mkdir, remove
from pathlib import Path
from queue import Queue
import subprocess
from tempfile import TemporaryDirectory
from typing import Any, List
from structlog import get_logger

from partisan.irods import DataObject, Collection


LOGGER = get_logger()


@dataclass
class LocalObject2:
    """Class to track the state of a file"""

    data_obj: DataObject
    local_name: str
    local_folder: Path
    is_local: bool = False
    is_remote: bool = True

    def download(self, tries=5):
        """Download the file to is local location.

        Args:
            tries: The max number of tries to attempt.
        """

        if self.is_local:
            raise Exception("Cannot download a LocalObject2 twice.")

        self.data_obj.get(Path(self.local_folder, self.local_name), tries=tries)
        self.is_local = True

    def upload(self, tries=5):
        """Upload the file to its remote location.

        Args:
            tries: the max number of tries to attempt.
        """

        if self.is_remote:
            raise Exception("Cannot upload a LocalObject2 twice.")

        if not self.is_local:
            raise Exception("Cannot upload a LocalObject2 which is not local.")

        self.data_obj.put(Path(self.local_folder, self.local_name), tries=tries)
        self.is_remote = True

    def remove_local_file(self):
        """Remove the file from local disk."""

        if not self.is_local:
            raise Exception("Cannot remove a file that is not local")

        remove(Path(self.local_folder, self.local_name))
        self.is_local = False


class Script:
    """A script to run on an input file and which produces an output file

    It must meet the following conditions:
        - the script must take one input folder
        - the script must produce output files in a folder named "output"
    """

    def __init__(self, path: PathLike) -> None:

        self.path = Path(path).resolve()

    def run(self, working_dir: PathLike):
        """Run the script.

        Args:
            working_dir: the path to the working directory for the script.

        Raises:
            CalledProcessError if the script returns with a non-zero exit status.
        """
        working_directory = Path(working_dir)
        input_folder = Path(working_dir, "input")
        LOGGER.debug(f"run script in directory {working_directory}")

        process = subprocess.run(
            [self.path, input_folder],
            cwd=working_directory,
            capture_output=True,
            check=True,
        )

        LOGGER.debug(process.stdout.decode())
        LOGGER.debug(process.stderr.decode())
        LOGGER.debug("script run")


class JobBatch:
    """An object used to track files being processed."""

    input_objs: List[LocalObject2]

    def __init__(self, scratch_location=None) -> None:
        self.input_objs = []

        # Set up temporary folders. We want to keep the TemporaryDirectory in the object,
        # so it gets destroyed at the same time as the JobBatch.
        # pylint: disable=consider-using-with
        self.tmp_dir = TemporaryDirectory(prefix="transponster-", dir=scratch_location)
        mkdir(Path(self.tmp_dir.name, "input"))
        mkdir(Path(self.tmp_dir.name, "output"))

    def get_output_objs(self, output_collection: Collection) -> List[LocalObject2]:
        """Get all objects to upload from the 'output' folder

        Args:
            output_collection: The destination iRODS Collection for the objects.

        Returns:
            A list of objects which will be uploaded to the intended iRODS location.
        """

        root = Path(self.tmp_dir.name, "output")
        objs: List[LocalObject2] = []

        for (dirpath, _, filenames) in os.walk(root):

            for fname in filenames:
                fpath = Path(root, dirpath)
                LOGGER.info(f"Adding {fpath}/{fname} to upload queue")
                data_obj = DataObject(Path(output_collection, fname))
                local_obj = LocalObject2(data_obj, fname, fpath, True, False)

                objs.append(local_obj)

        return objs

    def add_input_obj(self, obj: DataObject):
        """Add an object to the list of inputs

        Args:
            obj: the DataObject to add.
        """
        local_name = obj.name
        local_folder = self.input_folder_path
        local_object = LocalObject2(
            obj, local_name, local_folder, is_local=False, is_remote=True
        )
        self.input_objs.append(local_object)

    @property
    def input_folder_path(self):
        """Input folder path for this batch"""
        return Path(self.tmp_dir.name, "input")

    @property
    def output_folder_path(self):
        """Output folder path for this batch"""
        return Path(self.tmp_dir.name, "output")


class ErrorType(Enum):
    """Type of error a batch can fail with."""

    DOWNLOAD_FAILED = auto()
    PROCESSING_FAILED = auto()
    UPLOAD_FAILED = auto()
    FILE_NOT_FOUND = auto()
    PERMISSION_ERROR = auto()


@dataclass
class FailedJobBatch:
    """A failed Job Batch."""

    job_batch: JobBatch
    exception: Exception
    reason: ErrorType

    def cleanup_tmp(self):
        """Cleanup the temporary directory for the batch."""
        self.job_batch.tmp_dir.cleanup()

    def get_input_object_locations(self) -> List[str]:
        """Get the list of input files for the batch."""
        output = []
        for obj in self.job_batch.input_objs:
            output.append(obj.data_obj.name)
        return output

    def get_error_message(self) -> str:
        """Get the error message."""
        if self.reason == ErrorType.DOWNLOAD_FAILED:
            return f"Failed to download some inputs: {self.exception}"

        if self.reason == ErrorType.PROCESSING_FAILED:
            message = f"Failed to process some inputs: {self.exception}\n"
            message += f"\tstdout:\n{self.exception.stdout.decode()}\n"
            message += f"\tstderr:\n{self.exception.stderr.decode()}\n"
            return message

        if self.reason == ErrorType.UPLOAD_FAILED:
            return f"Failed to upload some inputs: {self.exception}"

        if self.reason == ErrorType.FILE_NOT_FOUND:
            return f"Failed to run a script: {self.exception}"

        if self.reason == ErrorType.PERMISSION_ERROR:
            return f"Permission error whilst running a script: {self.exception}"

        # Default case for linter
        return f"Unknown failure for some inputs: {self.exception}"


class ClosedException(Exception):
    """Just an Exception"""


class WrappedQueue:
    """Wrapper around a Queue which allows to signal closing the Queue."""

    _queue: Queue
    _closed: bool
    _put_event: Event
    _lock: Lock

    def __init__(self, maxsize: int = 0) -> None:
        self._queue = Queue(maxsize=maxsize)
        self._closed = False
        self._lock = Lock()
        self._put_event = Event()

    def put(self, item: Any):
        """Put an item into the queue.

        Args:
            item: the item to put
        """
        with self._lock:
            if self._closed:
                raise ClosedException("Cannot put to a closed WrappedQueue.")
        self._put_event.set()
        self._queue.put(item)

    def close(self):
        """Close the queue.

        Subsequent calls to put() will raise a ClosedException.
        Subsequent calls to get() will raise a ClosedException if the queue is empty.
        """
        with self._lock:
            self._closed = True
            self._put_event.set()

    def get(self):
        """Get the next item from the queue.

        Raises a ClosedException if the queue is both closed and empty.
        """
        if self._queue.empty():
            with self._lock:
                if self._queue.empty() and self._closed:
                    raise ClosedException("Queue is closed and empty")
            self._put_event.wait()
            self._put_event.clear()

        return self._queue.get()

    def empty(self) -> bool:
        """Is the queue empty."""
        return self._queue.empty()
