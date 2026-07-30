from django.test import SimpleTestCase, TestCase

from judge.models import ProblemData
from judge.models.tests.util import create_problem, create_problem_type, create_user
from judge.utils.problem_data import ProblemDataCompiler, scan_checker_source


class ScanCheckerSourceTestCase(SimpleTestCase):
    def test_clean_checker_passes(self):
        source = b"""
def check(process_output, judge_output, **kwargs):
    return process_output.strip() == judge_output.strip()
"""
        self.assertEqual(scan_checker_source(source), [])

    def test_flags_blacklisted_import(self):
        source = b"""
import os

def check(process_output, judge_output, **kwargs):
    return True
"""
        violations = scan_checker_source(source)
        self.assertIn("import 'os'", violations)

    def test_flags_blacklisted_from_import(self):
        source = b"""
from subprocess import run

def check(process_output, judge_output, **kwargs):
    return True
"""
        violations = scan_checker_source(source)
        self.assertIn("import 'subprocess'", violations)

    def test_flags_blacklisted_call(self):
        source = b"""
def check(process_output, judge_output, **kwargs):
    return eval(process_output) == judge_output
"""
        violations = scan_checker_source(source)
        self.assertIn("call to 'eval'", violations)

    def test_flags_multiple_violations(self):
        source = b"""
import socket
import ctypes

def check(process_output, judge_output, **kwargs):
    return __import__('os').system('echo hi')
"""
        violations = scan_checker_source(source)
        self.assertIn("import 'socket'", violations)
        self.assertIn("import 'ctypes'", violations)
        self.assertIn("call to '__import__'", violations)

    def test_flags_syntax_error(self):
        source = b'def check(process_output, judge_output, **kwargs:\n    return True'
        violations = scan_checker_source(source)
        self.assertEqual(len(violations), 1)
        self.assertIn('invalid Python syntax', violations[0])


class MakeInitCustomCheckerTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_user(username='author')
        create_problem_type(name='type')
        cls.problem = create_problem(code='initcheckerprob', types=('type',), authors=('author',))

    def test_custom_checker_writes_filename(self):
        data = ProblemData.objects.create(problem=self.problem, checker='custom')
        data.checker_file.name = 'initcheckerprob/checker.py'
        data.save()

        compiler = ProblemDataCompiler(self.problem, data, cases=[], files=[])
        init = compiler.make_init()

        self.assertEqual(init['checker'], 'checker.py')

    def test_custom_checker_with_args_writes_name_and_args(self):
        data = ProblemData.objects.create(problem=self.problem, checker='custom', checker_args='{"precision": 4}')
        data.checker_file.name = 'initcheckerprob/checker.py'
        data.save()

        compiler = ProblemDataCompiler(self.problem, data, cases=[], files=[])
        init = compiler.make_init()

        self.assertEqual(init['checker'], {'name': 'checker.py', 'args': {'precision': 4}})
