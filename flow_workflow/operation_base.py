from flow_workflow import io
import abc
import flow_workflow.log_manager
from flow_workflow.factory import load_operation


class Operation(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, net, name, operation_id, input_connections,
            output_properties, log_dir, parent_operation_id,
            child_operation_ids):
        self.net = net

        self.child_operation_ids = child_operation_ids
        self.input_connections = input_connections
        self.log_dir = log_dir
        self.name = name
        self.operation_id = operation_id
        self.output_properties = output_properties
        self.parent_operation_id = parent_operation_id

        self._cached_operations = {}

    def _child_id_from(self, name):
        return self.child_operation_ids[name]

    def child_named(self, name):
        return self._load_operation(self._child_id_from(name))

    def iter_children(self):
        for child_id in self.child_operation_ids.itervalues():
            yield self._load_operation(child_id)

    @property
    def net_key(self):
        return self.net.key

    @property
    def parent(self):
        return self._load_operation(self.parent_operation_id)

    @property
    def log_manager(self):
        return flow_workflow.log_manager.LogManager(operation_name=self.name,
                operation_id=self.operation_id, log_dir=self.log_dir)

    @property
    def input_names(self):
        result = []
        for props in self.input_connections.itervalues():
            result.extend(props.keys())
        return result

    def _determine_input_source(self, name):
        for source_op_id, property_dict in self.input_connections.iteritems():
            if name in property_dict:
                source_name = property_dict[name]
                return source_op_id, source_name
        raise KeyError("Property (%s) not found on operation (%s)" %
                (name, self.name))

    def _load_operation(self, operation_id):
        if int(operation_id) not in self._cached_operations:
            self._cached_operations[int(operation_id)] = load_operation(
                    net=self.net, operation_id=operation_id)

        return self._cached_operations[int(operation_id)]

    def load_inputs(self, parallel_id):
        return {name: self.load_input(name=name, parallel_id=parallel_id)
                for name in self.input_names}

    def load_outputs(self, parallel_id):
        return {name: self.load_output(name, parallel_id)
                for name in self.output_properties}

    def store_outputs(self, outputs, parallel_id):
        for name, value in outputs.iteritems():
            self.store_output(name, value, parallel_id)

    def load_input(self, name, parallel_id):
        source_op_id, source_name = self._determine_input_source(name)
        source_op = self._load_operation(source_op_id)
        return source_op.load_output(source_name, parallel_id)

    def store_input(self, name, value, parallel_id):
        source_op_id, source_name = self._determine_input_source(name)
        source_op = self._load_operation(source_op_id)
        source_op.store_output(source_name, value, parallel_id)

    @abc.abstractmethod
    def load_output(self, name, parallel_id):
        raise NotImplementedError()

    @abc.abstractmethod
    def store_output(self, name, value, parallel_id):
        raise NotImplementedError()


class NullOperation(Operation):
    def __init__(self, *args, **kwargs):
        pass

    @property
    def net_key(self):
        return None

    def load_output(self, name, parallel_id):
        pass

    def store_output(self, name, value, parallel_id):
        pass


class DirectStorageOperation(Operation):
    def load_output(self, name, parallel_id):
        return io.load_output(
                net=self.net,
                operation_id=self.operation_id,
                parallel_id=parallel_id,
                property_name=name)

    def store_output(self, name, value, parallel_id):
        io.store_output(
                net=self.net,
                operation_id=self.operation_id,
                parallel_id=parallel_id,
                property_name=name,
                value=value)

class PassThroughOperation(Operation):
    def load_output(self, name, parallel_id):
        return self.load_input(name, parallel_id)

    def store_output(self, name, value, parallel_id):
        return self.store_input(name, value, parallel_id)
