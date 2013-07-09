from flow.petri_net import future
from flow.petri_net.actions.base import BasicActionBase
from flow_workflow import io
from flow_workflow.operations import factory


class Workflow(object):
    def __init__(self, xml, inputs, resources):
        self.xml = xml
        self.inputs = inputs
        self.resources = resources

        self.dummy_operation = factory.operation('null')
        self._future_net = None

    def store_inputs(self, net):
        io.store_outputs(net, self.dummy_operation.operation_id, self.inputs)

    @property
    def input_connections(self):
        return {
            self.dummy_operation.operation_id:
                {name: name for name, value in self.inputs.iteritems()}
        }

    @property
    def output_properties(self):
        return self.operation.output_properties

    @property
    def operation(self):
        return factory.operation_from_xml(self.xml,
                parent=factory.operation('null'))

    @property
    def operation_future_net(self):
        return self.operation.net(self.input_connections,
                self.output_properties, self.resources)

    @property
    def future_net(self):
        if not self._future_net:
            self._future_net = WorkflowNet(self.operation_future_net)
        return self._future_net


class NotificationAction(BasicActionBase):
    required_args = ['status']

    def execute(self, net, color_descriptor, active_tokens, service_interfaces):
        deferred = service_interfaces['workflow_completion'].notify(
                net, status=self.args['status'])
        return [], deferred


class WorkflowNet(future.FutureNet):
    def __init__(self, operation_net):
        future.FutureNet.__init__(self)
        self.operation_net = operation_net

        self.start_place = self.add_place('start')
        self.subnets.add(operation_net)

        self.start_place.add_arc_out(operation_net.start_transition)

        self.notify_success_transition = self.add_basic_transition(
                name='notify_success_transition',
                action=future.FutureAction(
                    cls=NotificationAction, status='success'))

        self.notify_failure_transition = self.add_basic_transition(
                name='notify_failure_transition',
                action=future.FutureAction(
                    cls=NotificationAction, status='failure'))

        self.bridge_transitions(operation_net.success_transition,
                self.notify_success_transition,
                name='notify_success_place')

        self.bridge_transitions(operation_net.failure_transition,
                self.notify_failure_transition,
                name='notify_failure_place')
