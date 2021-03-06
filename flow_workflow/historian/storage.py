from collections import defaultdict, namedtuple
from flow.configuration.settings.injector import setting
from flow_workflow.historian.status import Status
from injector import inject
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.dialects.oracle import dialect as oracle_dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

import logging
import re


class CannotInsertError(RuntimeError):
    pass


LOG = logging.getLogger(__name__)


STATEMENTS_DICT = {}
STATEMENTS_DICT['insert_into_workflow_historian'] = """
INSERT INTO %s.workflow_historian (net_key, operation_id, color)
VALUES (:net_key, :operation_id, :color)
"""

STATEMENTS_DICT['update_workflow_historian'] = """
 UPDATE %s.workflow_historian SET workflow_instance_id = :workflow_instance_id
WHERE net_key=:net_key AND operation_id=:operation_id AND color=:color
"""

STATEMENTS_DICT['select_instance_id'] = """
    SELECT workflow_instance_id FROM %s.workflow_historian WHERE
net_key=:net_key AND operation_id=:operation_id AND color=:color
"""

STATEMENTS_DICT['select_execution_id'] = """
 SELECT current_execution_id FROM %s.workflow_instance WHERE
workflow_instance_id=:workflow_instance_id
"""

STATEMENTS_DICT['select_instance'] = """
    SELECT * from %s.workflow_instance
WHERE workflow_instance_id = :workflow_instance_id
FOR UPDATE
"""

STATEMENTS_DICT['select_execution'] = """
    SELECT * from %s.workflow_instance_execution
WHERE workflow_execution_id = :workflow_execution_id
FOR UPDATE
"""


TABLES = namedtuple('Tables', ['historian', 'instance', 'execution'])
SEQUENCES = namedtuple('Sequences', ['instance', 'execution'])
STATEMENTS = namedtuple('Statements', STATEMENTS_DICT.keys())

def on_oracle_connect(connection, record):
    cursor = connection.cursor()
    cursor.execute("alter session set NLS_DATE_FORMAT = "
            "'YYYY-MM-DD HH24:MI:SS'")
    cursor.execute("alter session set NLS_TIMESTAMP_FORMAT = "
            "'YYYY-MM-DD HH24:MI:SSXFF'")
    cursor.close()

@inject(connection_string=setting('workflow.historian.connection_string'),
        owner=setting('workflow.historian.owner'))
class WorkflowHistorianStorage(object):
    def __init__(self):
        self.statements = STATEMENTS(**{k:v % self.owner
                for k, v in STATEMENTS_DICT.items()})
        self.tables = TABLES(historian='%s.workflow_historian' % self.owner,
                instance='%s.workflow_instance' % self.owner,
                execution='%s.workflow_instance_execution' % self.owner)
        self.sequences = SEQUENCES(
                instance='%s.workflow_instance_seq' % self.owner,
                execution='%s.workflow_execution_seq' % self.owner)

        self.engine = create_engine(self.connection_string,
                case_sensitive=False, poolclass=StaticPool)

        # Oracle needs us to tell it to accept strings for dates/timestamps
        if isinstance(self.engine.dialect, oracle_dialect):
            event.listen(self.engine.pool, 'connect', on_oracle_connect)

    def update(self, update_info):
        LOG.debug("Updating '%s'", update_info['name'])

        transaction = SimpleTransaction(self.engine)
        try:
            instance_id = self._recursive_insert_or_update(transaction,
                    update_info)
        except:
            transaction.rollback()
            raise
        transaction.commit()

        return instance_id

    def _recursive_insert_or_update(self, transaction, update_info,
            recursion_level=0):
        LOG.debug("Attempting to insert or update '%s'", update_info['name'])
        if recursion_level > 1:
            raise RuntimeError("update should never recurse more than once!")

        try:
            instance_id = self._insert(transaction, update_info,
                    recursion_level)
            LOG.debug("Inserted '%s'", update_info['name'])
        except CannotInsertError:
            LOG.debug("Failed to insert %s into workflow_historian table, "
                    "attempting update instead.", update_info['operation_data'])
            instance_id = self._update(transaction, update_info,
                    recursion_level)
            LOG.debug("Updated '%s'", update_info['name'])

        return instance_id

    def _update(self, transaction, update_info, recursion_level):
        instance_id = self._get_instance_id(transaction,
                update_info['operation_data'])

        instance_row, execution_row = self._get_rows(transaction,
                instance_id)
        stored_status = Status(execution_row['STATUS'])
        new_status = update_info['status']
        should_overwrite = new_status.should_overwrite(stored_status)

        update_instance_dict = self._get_update_instance_dict(
                transaction      = transaction,
                recursion_level  = recursion_level,
                update_info      = update_info,
                instance_row     = instance_row,
                should_overwrite = should_overwrite)

        self._update_instance(transaction, update_instance_dict,
                instance_id)

        update_execution_dict = self._get_update_execution_dict(
                update_info      = update_info,
                execution_row    = execution_row,
                should_overwrite = should_overwrite)

        execution_id = instance_row['CURRENT_EXECUTION_ID']
        self._update_execution(transaction, update_execution_dict,
                execution_id)

        return instance_id

    def _update_instance(self, transaction, update_dict, instance_id):
        return _perform_update(transaction, update_dict,
                table_name = self.tables.instance,
                id_field   = "workflow_instance_id",
                update_id  = instance_id)

    def _update_execution(self, transaction, update_dict, execution_id):
        return _perform_update(transaction, update_dict,
                table_name=self.tables.execution,
                id_field="workflow_execution_id",
                update_id=execution_id)

    def _insert(self, transaction, update_info, recursion_level):
        try:
            execute_and_log(transaction,
                    self.statements.insert_into_workflow_historian,
                    operation_data = update_info['operation_data'])
        except IntegrityError:
            raise CannotInsertError("Couldn't insert into WORKFLOW_HISTORIAN "
                    "with %s" % update_info['operation_data'])

        # update workflow_historian table
        instance_id = self.next_instance_id(transaction)
        execute_and_log(transaction,
                self.statements.update_workflow_historian,
                operation_data = update_info['operation_data'],
                workflow_instance_id = instance_id)

        # insert into instance
        execution_id = self.next_execution_id(transaction)
        insert_instance_dict = {
                'WORKFLOW_INSTANCE_ID': instance_id,
        }

        insert_instance_dict.update(self._get_update_instance_dict(
                transaction      = transaction,
                recursion_level  = recursion_level,
                update_info      = update_info,
                instance_row     = None,
                should_overwrite = True))

        _perform_insert(transaction, insert_instance_dict,
                table_name=self.tables.instance)

        insert_execution_dict = self._get_update_execution_dict(
                update_info      = update_info,
                execution_row    = None,
                should_overwrite = True)
        insert_execution_dict['WORKFLOW_EXECUTION_ID'] = execution_id
        insert_execution_dict['WORKFLOW_INSTANCE_ID'] = instance_id

        _perform_insert(transaction, insert_execution_dict,
                table_name=self.tables.execution)

        self._update_instance(transaction,
                {'CURRENT_EXECUTION_ID': execution_id},
                instance_id)

        return instance_id

    @staticmethod
    def _next_id(transaction, sequence_name):
        NEXT_ID = "SELECT %s.nextval FROM DUAL"
        stmnt = NEXT_ID % sequence_name
        result = execute_and_log(transaction, stmnt)
        return result.fetchone()[0]

    def next_instance_id(self, transaction):
        return self._next_id(transaction, self.sequences.instance)

    def next_execution_id(self, transaction):
        return self._next_id(transaction, self.sequences.execution)

    def _get_rows(self, transaction, instance_id):
        """
        Return the row in the WORKFLOW_INSTANCE table and the
        WORKFLOW_INSTANCE_EXECUTION table
        """
        iresult = execute_and_log(transaction, self.statements.select_instance,
                workflow_instance_id=instance_id)
        instance_row = iresult.fetchone()

        execution_id = instance_row['CURRENT_EXECUTION_ID']

        eresult = execute_and_log(transaction, self.statements.select_execution,
                workflow_execution_id = execution_id)
        execution_row = eresult.fetchone()
        return instance_row, execution_row

    def _get_update_instance_dict(self, transaction, recursion_level,
            update_info, instance_row, should_overwrite):
        putative_dict = {}

        parent_operation_data = update_info.get('parent_operation_data')
        if parent_operation_data is not None:
            if update_info.get('is_subflow', None):
                putative_dict['PARENT_EXECUTION_ID'] = \
                        self._get_or_create_execution_id(
                            transaction, recursion_level,
                            operation_data   = parent_operation_data,
                            workflow_plan_id = update_info['workflow_plan_id'])

            else:
                putative_dict['PARENT_INSTANCE_ID'] = \
                        self._get_or_create_instance_id(
                            transaction, recursion_level,
                            operation_data   = parent_operation_data,
                            workflow_plan_id = update_info['workflow_plan_id'])

        peer_operation_data = update_info.get('peer_operation_data')
        if peer_operation_data is not None:
            putative_dict['PEER_INSTANCE_ID'] = self._get_or_create_instance_id(
                    transaction, recursion_level,
                    operation_data   = peer_operation_data,
                    workflow_plan_id = update_info['workflow_plan_id'])

        for var_name in ['PARALLEL_INDEX', 'WORKFLOW_PLAN_ID', 'NAME']:
            if update_info.get(var_name.lower(), None) is not None:
                putative_dict[var_name] = update_info[var_name.lower()]

        return self._generate_update_dict(putative_dict, row=instance_row,
                should_overwrite=should_overwrite)

    def _get_update_execution_dict(self, update_info,
            execution_row, should_overwrite):
        putative_dict = {}

        status = update_info['status']
        putative_dict['IS_RUNNING'] = status.is_running
        putative_dict['IS_DONE'] = status.is_done
        putative_dict['STATUS'] = status

        for var_name in ['DISPATCH_ID', 'START_TIME', 'END_TIME', 'STDOUT',
                'STDERR', 'EXIT_CODE', 'USER_NAME']:
            if update_info.get(var_name.lower(), None) is not None:
                putative_dict[var_name] = update_info[var_name.lower()]

        return self._generate_update_dict(putative_dict, row=execution_row,
                should_overwrite=should_overwrite)

    @staticmethod
    def _generate_update_dict(putative_dict,
            row              = None,
            should_overwrite = False):
        if row is None:
            row = defaultdict(lambda: None)

        update_dict = {}
        for column_name, value in putative_dict.items():
            if row[column_name] is None:
                update_dict[column_name] = value
            else:
                if should_overwrite and row[column_name] != value:
                    update_dict[column_name] = value
        return update_dict

    def _select_instance_id(self, transaction, operation_data):
        result = execute_and_log(transaction,
                self.statements.select_instance_id,
                operation_data=operation_data)
        rows = result.fetchall()
        if rows:
            instance_id = rows[0][0]
            if instance_id is not None:
                return instance_id
        return None

    def _get_instance_id(self, transaction, operation_data):
        instance_id = self._select_instance_id(transaction, operation_data)
        if instance_id is not None:
            return instance_id
        else:
            raise RuntimeError("Expected to find row in WORKFLOW_HISTORIAN"
                " table, but didn't!")

    def _get_or_create_instance_id(self, transaction, recursion_level,
            operation_data, workflow_plan_id):

        instance_id = self._select_instance_id(transaction, operation_data)
        if instance_id is not None:
            return instance_id
        else:
            update_info = {
                    'operation_data': operation_data,
                    'status':Status('unknown'),
                    'name':'unknown name operation_id=%d' %
                        operation_data.operation_id,
                    'workflow_plan_id': workflow_plan_id,
            }
            return self._recursive_insert_or_update(transaction, update_info,
                    recursion_level+1)

    def _get_or_create_execution_id(self, transaction, recursion_level,
            workflow_plan_id, operation_data):
        instance_id = self._get_or_create_instance_id(transaction,
                recursion_level  = recursion_level,
                operation_data   = operation_data,
                workflow_plan_id = workflow_plan_id)

        result = execute_and_log(transaction,
                self.statements.select_execution_id,
                workflow_instance_id=instance_id)
        execution_id = result.fetchone()[0]
        return execution_id


class SimpleTransaction(object):
    def __init__(self, engine):
        self.engine = engine
        self.conn = None
        self.trans = None

        try:
            self.conn, self.trans = self.begin_transaction()
        except:
            LOG.exception('Failed to create SimpleTransaction.')
            raise

    def begin_transaction(self):
        conn = self.engine.connect()
        trans = conn.begin()
        LOG.debug("Beginning transaction (%r) with connection %r.",
                self.trans, self.conn)
        return conn, trans

    def execute(self, *args, **kwargs):
        statement_kwargs = get_updated_statement_kwargs(**kwargs)
        return self.conn.execute(*args, **statement_kwargs)

    def commit(self, *args, **kwargs):
        LOG.debug("Commiting transaction")
        try:
            return_value = self.trans.commit(*args, **kwargs)
        except:
            LOG.exception('Failed to commit transaction')
            raise

        self._close()
        return return_value

    def rollback(self, *args, **kwargs):
        LOG.debug("Rolling back transaction.")
        return_value = self.trans.rollback(*args, **kwargs)
        self._close()
        return return_value

    def _close(self):
        self.conn.close()
        self.conn = None
        self.trans = None


def get_updated_statement_kwargs(**kwargs):
    STRINGIFY = ['STATUS']
    for string_key in STRINGIFY:
        if string_key in kwargs:
            kwargs[string_key] = str(kwargs[string_key])
    DICTIFY = ['operation_data']
    for dict_key in DICTIFY:
        if dict_key in kwargs:
            operation_data = kwargs.pop(dict_key)
            kwargs.update(operation_data.to_dict)
    return kwargs


def execute_and_log(transaction, statement, **kwargs):
    statement_kwargs = get_updated_statement_kwargs(**kwargs)
    log_statement(statement, **statement_kwargs)
    return transaction.execute(statement, **kwargs)


def log_statement(statement, **kwargs):
    debug_statement = statement
    for name, value in kwargs.items():
        debug_statement = re.sub(r':' + name, str(value), debug_statement)
    debug_statement = re.sub('\n', ' ', debug_statement)
    LOG.debug("EXECUTING: %s", debug_statement)


def _perform_insert(transaction, idict, table_name):
    INSERT = " INSERT INTO %s (%s) VALUES (%s)"

    names = ", ".join(idict.keys())
    place_holders = ", ".join([":%s" % x for x in idict.keys()])
    cmd = INSERT % (table_name, names, place_holders)

    execute_and_log(transaction, cmd, **idict)


def _perform_update(transaction, udict, table_name, id_field, update_id):
    if not udict:
        # nothing to update
        return None
    UPDATE = "    UPDATE %s SET %s WHERE %s=:%s"

    set_portion = ", ".join(["%s=:%s" % (x, x) for x in udict.keys()])
    cmd = UPDATE % (table_name, set_portion, id_field, id_field)
    udict[id_field] = update_id

    execute_and_log(transaction, cmd, **udict)


