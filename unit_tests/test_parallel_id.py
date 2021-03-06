from flow_workflow.parallel_id import ParallelIdentifier

import mock
import unittest


class ParallelIdentifierIndexTest(unittest.TestCase):
    def test_index_empty(self):
        pi = ParallelIdentifier()
        self.assertEqual(None, pi.index)

    def test_index_many(self):
        pi = ParallelIdentifier([(6, 2), (8, 3)])
        self.assertEqual(3, pi.index)


class ParallelIdentifierReferTest(unittest.TestCase):
    def setUp(self):
        self.pi = ParallelIdentifier([(6, 2), (8, 3)])

    def test_refers_to_true(self):
        operation = mock.Mock()
        operation.operation_id = 6

        self.assertTrue(self.pi.refers_to(operation))

    def test_refers_to_false(self):
        operation = mock.Mock()
        operation.operation_id = 2

        self.assertFalse(self.pi.refers_to(operation))


class ParallelIdentifierRepresenationTest(unittest.TestCase):
    def test_empty_list(self):
        pi = ParallelIdentifier([])
        self.assertEqual([], list(pi))

    def test_filled_list(self):
        pi = ParallelIdentifier([[6, 2], [8, 3]])
        self.assertEqual([(6, 2), (8, 3)], list(pi))


class ParallelIdentifierParentTest(unittest.TestCase):
    def test_no_parent(self):
        pi = ParallelIdentifier([])
        with self.assertRaises(KeyError):
            pi.parent_identifier

    def test_with_parent(self):
        pi = ParallelIdentifier([[6, 2], [8, 3]])
        self.assertEqual([(6, 2)], list(pi.parent_identifier))

    def test_parent_identifier_doesnt_modify_child(self):
        pi = ParallelIdentifier([[6, 2], [8, 3]])
        parent_identifier = pi.parent_identifier
        self.assertEqual([(6, 2), (8, 3)], list(pi))


class ParallelIdentifierChildTest(unittest.TestCase):
    def test_child_identifier(self):
        pi = ParallelIdentifier([])
        self.assertEqual([(6, 2)], list(pi.child_identifier(6, 2)))

    def test_child_identifier_doesnt_modify_parent(self):
        pi = ParallelIdentifier([])
        child_identifier = pi.child_identifier(6, 2)
        self.assertEqual([], list(pi))


class ParallelIdentifierIterationTest(unittest.TestCase):
    def test_basic_iteration(self):
        pi = ParallelIdentifier([[6, 2], [8, 3]])
        expected_outputs = [(6, 2), (8, 3)]
        for eo, ao in zip(expected_outputs, pi):
            self.assertEqual(eo, ao)

    def test_stack_iterator_empty(self):
        pi = ParallelIdentifier([])
        expected_outputs = [
            [],
        ]
        self.assertEqual(expected_outputs, map(list, pi.stack_iterator))

    def test_stack_iterator_full(self):
        pi = ParallelIdentifier([[4, 7], [6, 2], [8, 3]])
        expected_outputs = [
            [(4, 7), (6, 2), (8, 3)],
            [(4, 7), (6, 2)],
            [(4, 7)],
            [],
        ]
        self.assertEqual(expected_outputs, map(list, pi.stack_iterator))


    def test_cmp_equal(self):
        a = ParallelIdentifier([[4, 7], [6, 2], [8, 3]])
        b = ParallelIdentifier([[4, 7], [6, 2], [8, 3]])

        self.assertEqual(a, b)

    def test_cmp_not_equal(self):
        a = ParallelIdentifier([[4, 7], [6, 2], [8, 3]])
        b = ParallelIdentifier([[4, 7], [8, 3]])

        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
