import datetime
import os
import tempfile
from io import BytesIO
from zipfile import ZipFile

import yaml
from django.test import SimpleTestCase, TestCase

from judge.models import ProblemData, ProblemTestCase
from judge.models.tests.util import create_problem, create_problem_type, create_user
from judge.utils.problem_data import (
    MAX_IMPORTED_CASES, MAX_INIT_YML_SIZE, ParsedInit, ProblemDataCompiler, ProblemDataError,
    import_cases_from_zip, pair_zip_files, parse_init, read_zip_init_yml, scan_checker_source,
)


def make_zip(files):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as zip_file:
        for name, content in files.items():
            zip_file.writestr(name, content)
    return ZipFile(buffer)


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

    def test_flags_null_byte(self):
        source = b'def check():\x00\n    pass'
        violations = scan_checker_source(source)
        self.assertEqual(len(violations), 1)
        self.assertIn('invalid Python syntax', violations[0])

    def test_sys_argv_and_stdin_are_allowed(self):
        source = b"""
import sys

def check(process_output, judge_output, **kwargs):
    return sys.argv[1] == str(sys.stdin.read())
"""
        self.assertEqual(scan_checker_source(source), [])

    def test_sys_from_import_argv_and_stdin_are_allowed(self):
        source = b"""
from sys import argv, stdin

def check(process_output, judge_output, **kwargs):
    return argv[1] == str(stdin.read())
"""
        self.assertEqual(scan_checker_source(source), [])

    def test_flags_other_sys_attribute_access(self):
        source = b"""
import sys

def check(process_output, judge_output, **kwargs):
    sys.exit(1)
    return True
"""
        violations = scan_checker_source(source)
        self.assertIn("use of 'sys.exit'", violations)

    def test_flags_other_sys_from_import(self):
        source = b"""
from sys import exit

def check(process_output, judge_output, **kwargs):
    exit(1)
    return True
"""
        violations = scan_checker_source(source)
        self.assertIn("use of 'sys.exit'", violations)


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

    def test_custom_checker_without_file_raises_problem_data_error(self):
        data = ProblemData.objects.create(problem=self.problem, checker='custom')

        compiler = ProblemDataCompiler(self.problem, data, cases=[], files=[])
        with self.assertRaises(ProblemDataError):
            compiler.make_init()


class ReadZipInitYmlTestCase(SimpleTestCase):
    def test_read_returns_none_without_root_init(self):
        self.assertIsNone(read_zip_init_yml(make_zip({'sub/init.yml': 'test_cases: []'})))

    def test_read_parses_mapping(self):
        zip_file = make_zip({'init.yml': 'test_cases:\n- {in: 1.in, out: 1.out, points: 10}\n'})
        self.assertEqual(read_zip_init_yml(zip_file), {'test_cases': [{'in': '1.in', 'out': '1.out', 'points': 10}]})

    def test_read_rejects_oversized(self):
        with self.assertRaises(ProblemDataError):
            read_zip_init_yml(make_zip({'init.yml': 'a' * (MAX_INIT_YML_SIZE + 1)}))

    def test_read_rejects_non_mapping_and_invalid_yaml(self):
        for content in ('- 1\n- 2', '', ': [\n', 'a: 2001-13-45'):
            with self.subTest(content=content), self.assertRaises(ProblemDataError):
                read_zip_init_yml(make_zip({'init.yml': content}))

    def test_read_rejects_corrupt_and_encrypted_entries(self):
        for name, damage in (('corrupt', lambda info: setattr(info, 'CRC', info.CRC + 1)),
                             ('encrypted', lambda info: setattr(info, 'flag_bits', info.flag_bits | 0x1))):
            zip_file = make_zip({'init.yml': 'test_cases: []'})
            damage(zip_file.getinfo('init.yml'))
            with self.subTest(name), self.assertRaises(ProblemDataError):
                read_zip_init_yml(zip_file)


class ParseInitTestCase(SimpleTestCase):
    def test_parse_normal_and_pretest_cases(self):
        parsed = parse_init({
            'pretest_test_cases': [{'in': 's.in', 'out': 's.out', 'points': 0}],
            'test_cases': [{'in': '1.in', 'out': '1.out', 'points': 10}],
        })
        self.assertEqual(parsed.cases[0], {
            'order': 1, 'type': 'C', 'input_file': 's.in', 'output_file': 's.out', 'points': 0, 'is_pretest': True,
            'output_limit': None, 'output_prefix': None, 'checker': '', 'checker_args': '', 'generator_args': '',
            'batch_dependencies': '',
        })
        self.assertEqual(parsed.cases[1]['order'], 2)
        self.assertFalse(parsed.cases[1]['is_pretest'])
        self.assertEqual(parsed.cases[1]['points'], 10)

    def test_parse_batch(self):
        parsed = parse_init({
            'test_cases': [{'points': 30, 'dependencies': [1, 2], 'batched': [{'in': 'a.in', 'out': 'a.out'}]}],
        })
        self.assertEqual([case['type'] for case in parsed.cases], ['S', 'C', 'E'])
        self.assertEqual(parsed.cases[0]['points'], 30)
        self.assertEqual(parsed.cases[0]['batch_dependencies'], '1,2')
        self.assertIsNone(parsed.cases[1]['points'])
        self.assertEqual((parsed.cases[1]['input_file'], parsed.cases[1]['output_file']), ('a.in', 'a.out'))

    def test_parse_generator_args_and_per_case_checker(self):
        parsed = parse_init({'test_cases': [{
            'points': 1, 'generator_args': ['1', '2'], 'checker': {'name': 'floats', 'args': {'precision': 4}},
        }]})
        case = parsed.cases[0]
        self.assertEqual(case['generator_args'], '1\n2')
        self.assertEqual(case['checker'], 'floats')
        self.assertEqual(case['checker_args'], '{"precision": 4}')

    def test_parse_dataset_settings_only_for_present_keys(self):
        parsed = parse_init({
            'checker': {'name': 'floats', 'args': {'precision': 4}}, 'output_limit_length': 100, 'hints': ['unicode'],
        })
        self.assertIsNone(parsed.cases)
        self.assertEqual(parsed.settings, {
            'checker': 'floats', 'checker_args': '{"precision": 4}', 'output_limit': 100,
            'unicode': True, 'nobigmath': False,
        })
        self.assertEqual(parse_init({}), ParsedInit(None, {}, []))

    def test_parse_ignored_keys_warn(self):
        parsed = parse_init({'archive': 'x.zip', 'checker': 'weird.py', 'test_cases': []})
        self.assertTrue(any('archive' in warning for warning in parsed.warnings))
        self.assertTrue(any('weird.py' in warning for warning in parsed.warnings))
        self.assertNotIn('checker', parsed.settings)

    def test_parse_no_cases_leaves_cases_alone(self):
        for init in ({'test_cases': []}, {'test_cases': None}, {'pretest_test_cases': [], 'test_cases': None}):
            with self.subTest(init=init):
                self.assertIsNone(parse_init(init).cases)

    def test_parse_rejects_malformed_shapes(self):
        batch = {'points': 1, 'batched': []}
        for init in ({'test_cases': 5}, {'test_cases': [dict(batch, batched=5)]},
                     {'test_cases': [dict(batch, dependencies=5)]},
                     {'test_cases': [{'points': 1, 'generator_args': 5}]}, {'hints': 5},
                     {'test_cases': [{'points': float('inf')}]}, {'output_limit_length': float('inf')}):
            with self.subTest(init=init), self.assertRaises(ProblemDataError):
                parse_init(init)

    def test_parse_rejects_bad_values(self):
        for entry in ({'in': '1.in', 'out': '1.out', 'points': 'abc'}, {'in': 'a' * 101, 'out': '1.out', 'points': 1},
                      {'in': '1.in', 'out': '1.out', 'points': 99999999999999999999}):
            with self.subTest(entry=entry), self.assertRaises(ProblemDataError):
                parse_init({'test_cases': [entry]})

    def test_parse_rejects_unserializable_or_non_object_checker_args(self):
        for args in ({'d': datetime.date(2001, 1, 1)}, [1, 2]):
            with self.subTest(args=args), self.assertRaises(ProblemDataError):
                parse_init({'test_cases': [{'points': 1, 'checker': {'name': 'floats', 'args': args}}]})

    def test_parse_caps_rows_created_by_yaml_aliases(self):
        item_count = int(MAX_IMPORTED_CASES ** 0.5) + 1
        init = yaml.safe_load('i: &i {in: a, out: b}\nb: &b {points: 1, batched: [%s]}\ntest_cases: [%s]' % (
            ', '.join(['*i'] * item_count), ', '.join(['*b'] * item_count)))
        with self.assertRaises(ProblemDataError):
            parse_init(init)


class PairZipFilesTestCase(SimpleTestCase):
    def test_pair_zip_files(self):
        long_name = 'a' * 101 + '.in'
        names = ['10.in', '10.out', '2.in', '2.out', 'init.yml', 'data/', '__MACOSX/._2.in', '__MACOSX/._2.out',
                 'x.in', 'x.ans', long_name, '1\u00b2']
        self.assertEqual(pair_zip_files(names), ([('2.in', '2.out'), ('10.in', '10.out')],
                                                 ['1\u00b2', 'x.ans', 'x.in', long_name]))


CASE_FIELDS = ('order', 'type', 'input_file', 'output_file', 'generator_args', 'points', 'is_pretest',
               'output_prefix', 'output_limit', 'checker', 'checker_args', 'batch_dependencies')


class ImportCasesFromZipTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_user(username='author')
        create_problem_type(name='type')
        cls.problem = create_problem(code='zipimportprob', types=('type',), authors=('author',))
        cls.data = ProblemData.objects.create(problem=cls.problem)

    def make_zip_path(self, files):
        handle, path = tempfile.mkstemp(suffix='.zip')
        os.close(handle)
        self.addCleanup(os.remove, path)
        with ZipFile(path, 'w') as zip_file:
            for name, content in files.items():
                zip_file.writestr(name, content)
        return path

    def case_rows(self, problem=None):
        return list((problem or self.problem).cases.order_by('order').values_list(*CASE_FIELDS))

    def test_round_trip(self):
        rows = (
            dict(type='C', input_file='p.in', output_file='p.out', points=5, is_pretest=True),
            dict(type='S', points=30),
            dict(type='C', input_file='1.in', output_file='1.out', checker='floats',
                 checker_args='{"precision": 4}'),
            dict(type='C', input_file='2.in', output_file='2.out'),
            dict(type='E'),
            dict(type='S', points=20, batch_dependencies='1'),
            dict(type='C', input_file='3.in', output_file='3.out'),
            dict(type='E'),
            dict(type='C', input_file='4.in', output_file='4.out', points=10, output_limit=5),
        )
        for order, row in enumerate(rows, 1):
            row.setdefault('is_pretest', False)
            ProblemTestCase.objects.create(dataset=self.problem, order=order, **row)
        files = ['p.in', 'p.out'] + ['%d.%s' % (number, kind) for number in range(1, 5) for kind in ('in', 'out')]
        init = ProblemDataCompiler(self.problem, self.data, self.problem.cases.order_by('order'), files).make_init()
        other = create_problem(code='zipimportother', types=('type',), authors=('author',))
        other_data = ProblemData.objects.create(problem=other)

        path = self.make_zip_path(dict.fromkeys(files, 'x') | {'init.yml': yaml.safe_dump(init)})
        self.assertEqual(import_cases_from_zip(other, other_data, path), [])

        self.assertEqual(self.case_rows(other), self.case_rows())
        self.assertEqual(len(self.case_rows(other)), len(rows))

    def test_init_yml_replaces_cases(self):
        ProblemTestCase.objects.create(dataset=self.problem, order=1, input_file='old.in', is_pretest=False)
        path = self.make_zip_path({'init.yml': 'test_cases:\n- {in: 1.in, out: 1.out, points: 7}\n'})
        import_cases_from_zip(self.problem, self.data, path)
        self.assertEqual(self.problem.cases.count(), 1)
        self.assertEqual(self.problem.cases.get().input_file, '1.in')

    def test_absent_dataset_keys_keep_values(self):
        self.data.output_limit = 9
        self.data.checker = 'standard'
        self.data.save()
        path = self.make_zip_path({'init.yml': 'test_cases:\n- {in: 1.in, out: 1.out, points: 7}\n'})
        import_cases_from_zip(self.problem, self.data, path)
        self.data.refresh_from_db()
        self.assertEqual((self.data.output_limit, self.data.checker), (9, 'standard'))

    def test_init_yml_without_cases_keeps_rows(self):
        ProblemTestCase.objects.create(dataset=self.problem, order=1, input_file='old.in', is_pretest=False)
        before = self.case_rows()
        import_cases_from_zip(self.problem, self.data, self.make_zip_path({'init.yml': 'output_limit_length: 3'}))
        self.data.refresh_from_db()
        self.assertEqual(self.case_rows(), before)
        self.assertEqual(self.data.output_limit, 3)

    def test_init_yml_writes_only_imported_fields(self):
        self.data.feedback = 'unsaved'  # in-memory only; a full save would persist it
        import_cases_from_zip(self.problem, self.data, self.make_zip_path({'init.yml': 'output_limit_length: 3'}))
        stored = ProblemData.objects.get(pk=self.data.pk)
        self.assertEqual((stored.output_limit, stored.feedback), (3, ''))
        self.assertEqual(self.data.output_limit, 3)

    def test_no_yaml_empty_problem_registers_pairs(self):
        path = self.make_zip_path(dict.fromkeys(('10.in', '10.out', '2.in', '2.out'), 'x'))
        self.assertEqual(import_cases_from_zip(self.problem, self.data, path), [])
        self.assertEqual(list(self.problem.cases.order_by('order').values_list(
            'order', 'type', 'input_file', 'output_file', 'points', 'is_pretest')),
            [(1, 'C', '2.in', '2.out', None, False), (2, 'C', '10.in', '10.out', None, False)])

    def test_no_yaml_empty_zip_adds_nothing(self):
        self.assertEqual(import_cases_from_zip(self.problem, self.data, self.make_zip_path({})), [])
        self.assertEqual(self.problem.cases.count(), 0)

    def test_no_yaml_with_cases_adds_nothing(self):
        ProblemTestCase.objects.create(dataset=self.problem, order=1, input_file='1.in', output_file='1.out',
                                       is_pretest=False)
        path = self.make_zip_path(dict.fromkeys(('1.in', '1.out', '2.in', '2.out'), 'x'))
        warnings = import_cases_from_zip(self.problem, self.data, path)
        self.assertEqual(self.problem.cases.count(), 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn('2', warnings[0])

    def test_no_yaml_too_many_pairs_changes_nothing(self):
        names = ['%d.%s' % (number, kind) for number in range(MAX_IMPORTED_CASES + 1) for kind in ('in', 'out')]
        with self.assertRaises(ProblemDataError):
            import_cases_from_zip(self.problem, self.data, self.make_zip_path(dict.fromkeys(names, 'x')))
        self.assertEqual(self.problem.cases.count(), 0)

    def test_unpaired_files_warn(self):
        path = self.make_zip_path(dict.fromkeys(('1.in', '1.out', 'x.ans'), 'x'))
        warnings = import_cases_from_zip(self.problem, self.data, path)
        self.assertEqual(self.problem.cases.count(), 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn('1', warnings[0])

    def test_generator_skips_registration(self):
        self.data.generator.name = 'code/gen.py'
        self.data.save()
        path = self.make_zip_path(dict.fromkeys(('1.in', '1.out'), 'x'))
        import_cases_from_zip(self.problem, self.data, path)
        self.assertEqual(self.problem.cases.count(), 0)

    def test_invalid_yaml_changes_nothing(self):
        ProblemTestCase.objects.create(dataset=self.problem, order=1, input_file='old.in', is_pretest=False)
        before = self.case_rows()
        with self.assertRaises(ProblemDataError):
            import_cases_from_zip(self.problem, self.data, self.make_zip_path({'init.yml': '- 1'}))
        self.assertEqual(self.case_rows(), before)
