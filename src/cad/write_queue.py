"""One consumer, one COM apartment per operation, no CAD worker pool."""
from concurrent.futures import ThreadPoolExecutor


class SingleWriter:
    def __init__(self):
        self._consumer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cad-writer")

    def run(self, function, *args, **kwargs):
        return self._consumer.submit(function, *args, **kwargs).result()

    def close(self):
        self._consumer.shutdown(wait=True)


WRITE_QUEUE = SingleWriter()
