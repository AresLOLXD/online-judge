import ast
import json
import os
import re
import zlib
from collections import namedtuple
from typing import Iterable, List, Optional, Tuple
from zipfile import BadZipFile, ZipFile

import yaml
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import transaction
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext

if os.altsep:
    def split_path_first(path, repath=re.compile('[%s]' % re.escape(os.sep + os.altsep))):
        return repath.split(path, 1)
else:
    def split_path_first(path):
        return path.split(os.sep, 1)


DANGEROUS_CHECKER_IMPORTS = frozenset((
    'os', 'subprocess', 'socket', 'shutil', 'ctypes', 'importlib',
    'multiprocessing', 'threading', 'requests', 'urllib', 'http', 'ftplib',
    'telnetlib', 'pty', 'pickle', 'marshal', 'code',
))

DANGEROUS_CHECKER_CALLS = frozenset(('eval', 'exec', 'compile', '__import__'))

# `sys` is otherwise blacklisted, but checkers legitimately need it to read
# the judge's input (sys.stdin/sys.argv) - only these two attributes are
# allowed, everything else on sys (sys.exit, sys.settrace, ...) is flagged.
SYS_ALLOWED_ATTRS = frozenset(('argv', 'stdin'))


def scan_checker_source(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as e:
        return ['invalid Python syntax: %s' % e]

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split('.')[0]
                if root in DANGEROUS_CHECKER_IMPORTS:
                    violations.append("import '%s'" % root)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or '').split('.')[0]
            if root == 'sys':
                for alias in node.names:
                    if alias.name not in SYS_ALLOWED_ATTRS:
                        violations.append("use of 'sys.%s'" % alias.name)
            elif root in DANGEROUS_CHECKER_IMPORTS:
                violations.append("import '%s'" % root)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DANGEROUS_CHECKER_CALLS:
                violations.append("call to '%s'" % node.func.id)
        elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and
                node.value.id == 'sys' and node.attr not in SYS_ALLOWED_ATTRS):
            violations.append("use of 'sys.%s'" % node.attr)

    return violations


class ProblemDataStorage(FileSystemStorage):
    def __init__(self):
        super(ProblemDataStorage, self).__init__(settings.DMOJ_PROBLEM_DATA_ROOT)

    def url(self, name):
        path = split_path_first(name)
        if len(path) != 2:
            raise ValueError('This file is not accessible via a URL.')
        return reverse('problem_data_file', args=path)

    def _save(self, name, content):
        if self.exists(name):
            self.delete(name)
        return super(ProblemDataStorage, self)._save(name, content)

    def get_available_name(self, name, max_length=None):
        return name

    def rename(self, old, new):
        return os.rename(self.path(old), self.path(new))


class ProblemDataError(Exception):
    def __init__(self, message):
        super(ProblemDataError, self).__init__(message)
        self.message = message


INIT_YML_NAME = 'init.yml'
# shortcut: 1 MiB cap on the bundled init.yml, raise it if a real dataset needs a larger one.
MAX_INIT_YML_SIZE = 1 << 20
MAX_FILE_NAME_LENGTH = 100  # ProblemTestCase.input_file / output_file max_length

ParsedInit = namedtuple('ParsedInit', 'cases settings warnings')

ENTRY_KEYS = frozenset((
    'in', 'out', 'points', 'generator_args', 'output_limit_length', 'output_prefix_length', 'checker',
    'batched', 'dependencies',
))
TOP_LEVEL_KEYS = frozenset((
    'test_cases', 'pretest_test_cases', 'output_limit_length', 'output_prefix_length', 'checker', 'hints',
))


def read_zip_init_yml(zip_file: ZipFile) -> Optional[dict]:
    try:
        info = zip_file.getinfo(INIT_YML_NAME)
    except KeyError:
        return None
    if info.file_size > MAX_INIT_YML_SIZE:
        raise ProblemDataError(_('init.yml is too large (limit: %d bytes).') % MAX_INIT_YML_SIZE)
    try:
        init = yaml.safe_load(zip_file.read(info))
    except (BadZipFile, EOFError, NotImplementedError, RuntimeError, zlib.error, yaml.YAMLError,
            ValueError) as e:
        # RuntimeError also covers encrypted entries and RecursionError from deeply nested yaml;
        # ValueError covers impossible timestamps such as 2001-13-45
        raise ProblemDataError(_('init.yml could not be parsed: %s') % e)
    if not isinstance(init, dict):
        raise ProblemDataError(_('init.yml must be a mapping.'))
    return init


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        raise ProblemDataError(_('Expected an integer in init.yml, got: %s') % (value,))


def _as_list(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProblemDataError(_('Expected a list in init.yml, got: %s') % (value,))
    return value


def _parse_checker(value, warnings):
    """Return (name, json args) for a supported checker, else warn and return ('', '')."""
    from judge.models.problem_data import CHECKERS

    name, args = (value.get('name'), value.get('args')) if isinstance(value, dict) else (value, None)
    if name not in [checker for checker, _label in CHECKERS]:
        warnings.append(_('Checker %s is not supported and was ignored.') % (name,))
        return '', ''
    return name, json.dumps(args) if args else ''


def _parse_entry(entry, is_pretest, warnings, unknown_keys):
    if not isinstance(entry, dict):
        raise ProblemDataError(_('Every test case in init.yml must be a mapping.'))
    unknown_keys.update(str(key) for key in entry if key not in ENTRY_KEYS)
    row = {'is_pretest': is_pretest}
    for key, field in (('in', 'input_file'), ('out', 'output_file')):
        row[field] = str(entry.get(key, ''))
        if len(row[field]) > MAX_FILE_NAME_LENGTH:
            raise ProblemDataError(_('File name is too long: %s') % row[field])
    for key, field in (('points', 'points'), ('output_limit_length', 'output_limit'),
                       ('output_prefix_length', 'output_prefix')):
        row[field] = _to_int(entry[key]) if entry.get(key) is not None else None
    row['generator_args'] = '\n'.join(map(str, _as_list(entry.get('generator_args'))))
    row['checker'], row['checker_args'] = _parse_checker(entry['checker'], warnings) if 'checker' in entry else ('', '')
    return row


def parse_init(init: dict) -> ParsedInit:
    """Inverse of ProblemDataCompiler.make_init(): turn a bundled init.yml into form data."""
    warnings = []
    unknown_keys = set(map(str, init.keys() - TOP_LEVEL_KEYS))
    cases = []

    def add(type, is_pretest, **fields):
        cases.append(dict({
            'order': len(cases) + 1, 'type': type, 'input_file': '', 'output_file': '', 'points': None,
            'is_pretest': is_pretest, 'output_limit': None, 'output_prefix': None, 'checker': '',
            'checker_args': '', 'generator_args': '', 'batch_dependencies': '',
        }, **fields))

    for key, is_pretest in (('pretest_test_cases', True), ('test_cases', False)):
        for entry in _as_list(init.get(key)):
            row = _parse_entry(entry, is_pretest, warnings, unknown_keys)
            if 'batched' not in entry:
                add('C', **row)
                continue
            # shortcut: dependencies are imported as written, not renumbered; the compiler rejects invalid ones.
            dependencies = ','.join(str(_to_int(number)) for number in _as_list(entry.get('dependencies')))
            add('S', **dict(row, batch_dependencies=dependencies, input_file='', output_file=''))
            for item in _as_list(entry['batched']):
                add('C', **dict(_parse_entry(item, is_pretest, warnings, unknown_keys), points=None))
            add('E', is_pretest)

    settings = {}
    for key, field in (('output_limit_length', 'output_limit'), ('output_prefix_length', 'output_prefix')):
        if init.get(key) is not None:
            settings[field] = _to_int(init[key])
    if 'checker' in init:
        checker, checker_args = _parse_checker(init['checker'], warnings)
        if checker:
            settings.update(checker=checker, checker_args=checker_args)
    if 'hints' in init:
        hints = _as_list(init['hints'])
        settings.update(unicode='unicode' in hints, nobigmath='nobigmath' in hints)

    if unknown_keys:
        warnings.insert(0, _('Ignored init.yml keys: %s') % ', '.join(sorted(unknown_keys)))
    # no cases in the yaml means leave the problem's existing cases alone
    return ParsedInit(cases or None, settings, warnings)


def pair_zip_files(names: Iterable[str]) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Pair input files with their output file using the rule of the data page's JavaScript autofill."""
    names = [name for name in names
             if not name.endswith('/') and name != INIT_YML_NAME and not name.startswith('__MACOSX/')]
    available = set(names)
    pairs = []
    for name in names:
        output = re.sub(r'in(?!.*?in)', 'out', name)
        if output != name and output in available and max(len(name), len(output)) <= MAX_FILE_NAME_LENGTH:
            pairs.append((name, output))
    used = {name for pair in pairs for name in pair}

    def natural_key(name):
        return len(name) > MAX_FILE_NAME_LENGTH, [int(part) if part.isdigit() else part
                                                  for part in re.split(r'(\d+)', name)]

    return (sorted(pairs, key=lambda pair: natural_key(pair[0])),
            sorted((name for name in names if name not in used), key=natural_key))


def import_cases_from_zip(problem, data, zip_path: str) -> List[str]:
    """Apply a data zip to a problem and return warnings; ProblemDataError is raised before any DB change."""
    from judge.models import ProblemTestCase

    with ZipFile(zip_path) as zip_file:
        init = read_zip_init_yml(zip_file)
        names = zip_file.namelist()
    parsed = parse_init(init) if init is not None else None
    pairs, unpaired = pair_zip_files(names)

    warnings = []
    with transaction.atomic():
        if parsed is not None:
            warnings = parsed.warnings
            if parsed.cases is not None:
                problem.cases.all().delete()
                ProblemTestCase.objects.bulk_create(ProblemTestCase(dataset=problem, **case) for case in parsed.cases)
            for field, value in parsed.settings.items():
                setattr(data, field, value)
            data.save()
        elif problem.cases.exists():
            used = {file for case in problem.cases.all() for file in (case.input_file, case.output_file)}
            unused = len(({name for pair in pairs for name in pair} | set(unpaired)) - used)
            if unused:
                warnings.append(ngettext('%d file in the zip is not used by any test case.',
                                         '%d files in the zip are not used by any test case.', unused) % unused)
        elif not data.generator:
            ProblemTestCase.objects.bulk_create(
                ProblemTestCase(dataset=problem, order=order, input_file=input_file, output_file=output_file,
                                is_pretest=False)
                for order, (input_file, output_file) in enumerate(pairs, 1)
            )
            if unpaired:
                warnings.append(ngettext('%d file in the zip could not be paired as input and output and was ignored.',
                                         '%d files in the zip could not be paired as input and output and were '
                                         'ignored.', len(unpaired)) % len(unpaired))
    return warnings


class ProblemDataCompiler(object):
    def __init__(self, problem, data, cases, files):
        self.problem = problem
        self.data = data
        self.cases = cases
        self.files = files

        self.generator = data.generator

    def resolve_checker_name(self, checker_field):
        if checker_field != 'custom':
            return checker_field
        if not self.data.checker_file:
            raise ProblemDataError(_('A custom checker was selected but no checker file is attached.'))
        checker_path = split_path_first(self.data.checker_file.name)
        if len(checker_path) != 2:
            raise ProblemDataError(_('How did you corrupt the checker file path?'))
        return checker_path[1]

    def make_init(self):
        cases = []
        batch = None
        batch_count = 0

        def end_batch():
            if not batch['batched']:
                raise ProblemDataError(_('Empty batches not allowed.'))
            cases.append(batch)

        def make_checker(case):
            checker_name = self.resolve_checker_name(case.checker)
            if case.checker_args:
                return {
                    'name': checker_name,
                    'args': json.loads(case.checker_args),
                }
            return checker_name

        for i, case in enumerate(self.cases, 1):
            if case.type == 'C':
                data = {}
                if batch:
                    case.points = None
                    case.is_pretest = batch['is_pretest']
                else:
                    if case.points is None:
                        raise ProblemDataError(_('Points must be defined for non-batch case #%d.') % i)
                    data['is_pretest'] = case.is_pretest

                if not self.generator:
                    if case.input_file not in self.files:
                        raise ProblemDataError(_('Input file for case %d does not exist: %s') %
                                               (i, case.input_file))
                    if case.output_file not in self.files:
                        raise ProblemDataError(_('Output file for case %d does not exist: %s') %
                                               (i, case.output_file))

                if case.input_file:
                    data['in'] = case.input_file
                if case.output_file:
                    data['out'] = case.output_file
                if case.points is not None:
                    data['points'] = case.points
                if case.generator_args:
                    data['generator_args'] = case.generator_args.splitlines()
                if case.output_limit is not None:
                    data['output_limit_length'] = case.output_limit
                if case.output_prefix is not None:
                    data['output_prefix_length'] = case.output_prefix
                if case.checker:
                    data['checker'] = make_checker(case)
                else:
                    case.checker_args = ''
                case.save(update_fields=('checker_args', 'is_pretest'))
                (batch['batched'] if batch else cases).append(data)
            elif case.type == 'S':
                batch_count += 1
                if batch:
                    end_batch()
                if case.points is None:
                    raise ProblemDataError(_('Batch start case #%d requires points.') % i)
                dependencies = []
                if case.batch_dependencies.strip():
                    try:
                        dependencies = list(map(int, case.batch_dependencies.split(',')))
                    except ValueError:
                        raise ProblemDataError(
                            _('Dependencies must be a comma-separated list of integers for batch start case #%d.') % i,
                        )
                    for batch_number in dependencies:
                        if batch_number >= batch_count:
                            raise ProblemDataError(
                                _('Dependencies must depend on previous batches for batch start case #%d.') % i,
                            )
                        elif batch_number < 1:
                            raise ProblemDataError(_('Dependencies must be positive for batch start case #%d.') % i)
                batch = {
                    'points': case.points,
                    'batched': [],
                    'is_pretest': case.is_pretest,
                    'dependencies': dependencies,
                }
                if case.generator_args:
                    batch['generator_args'] = case.generator_args.splitlines()
                if case.output_limit is not None:
                    batch['output_limit_length'] = case.output_limit
                if case.output_prefix is not None:
                    batch['output_prefix_length'] = case.output_prefix
                if case.checker:
                    batch['checker'] = make_checker(case)
                else:
                    case.checker_args = ''
                case.input_file = ''
                case.output_file = ''
                case.save(update_fields=('checker_args', 'input_file', 'output_file'))
            elif case.type == 'E':
                if not batch:
                    raise ProblemDataError(_('Attempt to end batch outside of one in case #%d.') % i)
                case.is_pretest = batch['is_pretest']
                case.input_file = ''
                case.output_file = ''
                case.generator_args = ''
                case.checker = ''
                case.checker_args = ''
                case.save()
                end_batch()
                batch = None
        if batch:
            end_batch()

        init = {}

        if self.data.zipfile:
            zippath = split_path_first(self.data.zipfile.name)
            if len(zippath) != 2:
                raise ProblemDataError(_('How did you corrupt the zip path?'))
            init['archive'] = zippath[1]

        if self.generator:
            generator_path = split_path_first(self.generator.name)
            if len(generator_path) != 2:
                raise ProblemDataError(_('How did you corrupt the generator path?'))
            init['generator'] = generator_path[1]

        pretest_test_cases = []
        test_cases = []
        hints = []

        for case in cases:
            if case['is_pretest']:
                pretest_test_cases.append(case)
            else:
                test_cases.append(case)

            del case['is_pretest']

        if pretest_test_cases:
            init['pretest_test_cases'] = pretest_test_cases
        if test_cases:
            init['test_cases'] = test_cases
        if self.data.output_limit is not None:
            init['output_limit_length'] = self.data.output_limit
        if self.data.output_prefix is not None:
            init['output_prefix_length'] = self.data.output_prefix
        if self.data.unicode:
            hints.append('unicode')
        if self.data.nobigmath:
            hints.append('nobigmath')
        if self.data.checker:
            init['checker'] = make_checker(self.data)
        else:
            self.data.checker_args = ''

        if hints:
            init['hints'] = hints

        return init

    def compile(self):
        from judge.models import problem_data_storage

        yml_file = '%s/init.yml' % self.problem.code
        try:
            init = self.make_init()
            if init:
                init = yaml.safe_dump(init)
        except ProblemDataError as e:
            self.data.feedback = e.message
            self.data.save()
            problem_data_storage.delete(yml_file)
        else:
            self.data.feedback = ''
            self.data.save()
            if init:
                problem_data_storage.save(yml_file, ContentFile(init))
            else:
                # Don't write empty init.yml since we should be looking in manually managed
                # judge-server#670 will not update cache on empty init.yml,
                # but will do so if there is no init.yml, so we delete the init.yml
                problem_data_storage.delete(yml_file)

    @classmethod
    def generate(cls, *args, **kwargs):
        self = cls(*args, **kwargs)
        self.compile()
