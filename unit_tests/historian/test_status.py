from unittest import TestCase, main
from flow_workflow.historian.status import Status, VALID_STATUSES


class StatusTests(TestCase):
    def test_validate_success(self):
        new_status = Status('unknown')
        new_status.validate()

    def test_validate_fail(self):
        with self.assertRaises(ValueError):
            Status('bad_status')

    def test_should_overwrite(self):
        new = Status('new')
        scheduled = Status('scheduled')

        self.assertTrue(scheduled.should_overwrite(new))
        self.assertFalse(new.should_overwrite(scheduled))
        self.assertFalse(new.should_overwrite(new))

    def test_is_running(self):
        self.assertTrue(Status('running').is_running)
        self.assertTrue(Status('scheduled').is_running)
        self.assertFalse(Status('new').is_running)

    def test_is_done(self):
        self.assertTrue(Status('done').is_done)
        self.assertFalse(Status('new').is_done)
