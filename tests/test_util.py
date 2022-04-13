from pathlib import Path

import os
from subprocess import SubprocessError
from transponster.util import LocalObject2, Script, WrappedQueue, ClosedException
from pytest import raises
from partisan.irods import DataObject


class TestWrappedQueue:
    def test_empty_closed(self):

        queue = WrappedQueue()
        queue.close()
        with raises(ClosedException):
            queue.get()

    def test_not_empty_closed(self):

        queue = WrappedQueue()
        queue.put("Hello")
        queue.close()
        assert queue.get() == "Hello"
        with raises(ClosedException):
            queue.get()

    def test_fail_put_to_closed_queue(self):

        queue = WrappedQueue()
        queue.close()
        with raises(ClosedException):
            queue.put("Fail")


class TestScript:
    def test_run(self, script_working_dir):
        """Test running a script."""
        script = Script("./tests/data/scripts/hello_output.sh")
        script.run(script_working_dir)

        # Check that new file is created containing a message
        output_file_location = Path(script_working_dir, "output", "output.txt")
        assert os.path.exists(output_file_location)
        with open(output_file_location, "r") as actual_file:

            assert actual_file.read() == "Hello, world!\n"

    def test_failed_script(self, script_working_dir):
        """Test a failing script"""

        script = Script("./tests/data/scripts/fail.sh")

        with raises(SubprocessError):
            script.run(script_working_dir)


class TestLocalObject2:
    """Tests for the TestLocalObject2 class"""

    def test_remove_object(self, script_working_dir):
        """Test removing an object from local storage."""

        to_delete_path = Path(script_working_dir, "input/to_delete.txt")

        open(to_delete_path, "a").close()

        localobj2 = LocalObject2(
            None,
            "to_delete.txt",
            Path(script_working_dir, "input"),
            is_local=True,
            is_remote=False,
        )

        localobj2.remove_local_file()

        assert not localobj2.is_local

        assert not os.path.exists(to_delete_path)

        with raises(Exception, match="Cannot remove a file that is not local"):
            localobj2.remove_local_file()

    def test_download_object(self, script_working_dir, irods_inputs):
        """Test downloading an object from iRODS."""

        _ = irods_inputs
        input_folder = Path(script_working_dir, "input")

        localobj2 = LocalObject2(
            DataObject("/testZone/home/irods/datafiles/2.txt"),
            "input.txt",
            input_folder,
        )

        localobj2.download()

        assert localobj2.is_local

        local_fname = Path(input_folder, localobj2.local_name)
        assert os.path.exists(local_fname)

        with open(local_fname, "r") as local_file:

            assert local_file.read() == "File number 2"

        # Downloading again should raise exception
        with raises(Exception):
            localobj2.download()

    def test_upload_object(self, script_working_dir):
        """Test uploading an object to iRODS."""

        localobj2 = LocalObject2(
            DataObject("/testZone/home/irods/destination.txt"),
            local_name="2.txt",
            local_folder="tests/data/datafiles",
            is_local=True,
            is_remote=False,
        )

        localobj2.upload()

        assert localobj2.data_obj.exists()

        redownloaded_path = Path(script_working_dir, "destination.txt")
        localobj2.data_obj.get(redownloaded_path)
        with open(redownloaded_path, "r") as redownloaded:
            assert redownloaded.read() == "File number 2"

    def test_upload_nonexistent_file(self):
        """Test uploading a nonexistent file."""

        localobj2 = LocalObject2(
            None,
            "doesnotexist",
            "/definitelydoesntexist",
            is_local=True,
            is_remote=False,
        )

        with raises(Exception):
            localobj2.upload()


class TestJobBatch:
    def test_output_objs_getter(self):
        """Test getting all output from JobBatch."""
        # TODO
        pass

    def test_add_input_obj(self):
        """Test adding an input object to JobBatch."""
        # TODO
        pass

    def test_input_folder_path(self):
        """Test correct input folder path."""
        # TODO
        pass

    def test_output_folder_path(self):
        """Test correct output folder path."""
        # TODO
        pass
