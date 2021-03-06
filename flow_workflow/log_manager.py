import os
import re


LOG_NAME_TEMPLATE = '%(base_name)s.%(operation_id)s'
MAX_BASE_NAME_LEN = 256


class LogManager(object):
    def __init__(self, log_dir, operation_id, operation_name):
        self.log_dir = log_dir
        self.operation_id = operation_id
        self.operation_name = operation_name

    def stderr_log_path(self, parallel_id):
        return self._resolve_log_path(suffix='err', parallel_id=parallel_id)

    def stdout_log_path(self, parallel_id):
        return self._resolve_log_path(suffix='out', parallel_id=parallel_id)

    @property
    def base_name(self):
        bname = re.sub("[^A-Za-z0-9_.-]+", "_",
                self.operation_name)[:MAX_BASE_NAME_LEN]
        return re.sub("^_*|_*$", "", bname)

    def _resolve_log_path(self, suffix, parallel_id):
        if not self.log_dir:
            return None

        template_args = {
                'base_name': self.base_name,
                'operation_id': self.operation_id,
        }
        filename_components = [LOG_NAME_TEMPLATE % template_args]
        filename_components.extend(self._serialize_parallel_id(parallel_id))
        filename_components.append(suffix)

        filename = '.'.join(filename_components)

        return os.path.join(self.log_dir, filename)

    def _serialize_parallel_id(self, parallel_id):
        return ['%d_%d' % (op_id, par_idx) for op_id, par_idx in parallel_id]
