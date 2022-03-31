"""Processing thread."""

from pathlib import Path
from queue import Queue
from threading import Thread
from shutil import rmtree

from structlog import get_logger

from transponster.util import (
    ClosedException,
    ErrorType,
    FailedJobBatch,
    JobBatch,
    Script,
    WrappedQueue,
)


class ProcessingThread(Thread):
    """Run scripts on inputs and send to upload thread."""

    def __init__(
        self,
        downloaded: WrappedQueue,
        to_upload: WrappedQueue,
        error_queue: Queue,
        script_to_run: Script,
    ):
        Thread.__init__(self)

        self.downloaded = downloaded
        self.to_upload = to_upload
        self.error_queue = error_queue
        self.script = script_to_run
        self.done = False
        self.logger = get_logger()

    def run(self):

        while not (self.downloaded.empty() and self.done):
            self.logger.info("Waiting for next batch to process")
            try:
                job_batch: JobBatch = self.downloaded.get()
            except ClosedException:
                self.done = True
                break

            if job_batch is None:
                self.logger.info("Processing: Batch is empty do to previous error")
                self.to_upload.put(None)
                continue
            self.logger.info(f"Got batch at folder {job_batch.tmp_dir.name}")
            working_dir = Path(job_batch.tmp_dir.name).resolve()
            input_folder_path = job_batch.input_folder_path

            self.logger.info(f"Running script on {working_dir}")
            try:
                self.script.run(working_dir)
            except Exception as exception:
                failed_batch = FailedJobBatch(
                    job_batch, exception.__repr__(), ErrorType.PROCESSING_FAILED
                )
                self.logger.error(failed_batch.get_error_message())
                self.error_queue.put(failed_batch)
                self.to_upload.put(None)
                continue

            self.logger.info(
                f"Finished running script on {working_dir}, removing input"
            )
            # Delete input file once done
            rmtree(input_folder_path)

            # Send the batch to the upload_thread
            self.to_upload.put(job_batch)

        self.to_upload.close()
        self.logger.info("Processing thread done")
