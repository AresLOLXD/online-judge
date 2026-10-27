import io
import os
import shutil
import tempfile
import zipfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from judge.models import ProblemData, ProblemTestCase, problem_data_storage
from judge.models.tests.util import create_problem, create_problem_type, create_user

MEDIA_ROOT = tempfile.mkdtemp()
STATIC_ROOT = tempfile.mkdtemp()
ONE_CASE_INIT = 'test_cases:\n- {in: 1.in, out: 1.out, points: 10}\n'


def make_zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zip_file:
        for name, content in files.items():
            zip_file.writestr(name, content)
    return buffer.getvalue()


def renders_pages(test_class):
    """Let pages render without built assets: an empty JS catalog in a temp STATIC_ROOT, compressor disabled.

    Also stubs the test client's context capture, which crashes copying Django contexts on Python 3.14
    (response.context is unavailable; assert on the HTML instead).
    """
    test_class = override_settings(STATIC_ROOT=STATIC_ROOT, COMPRESS_ENABLED=False)(test_class)
    test_class = patch('django.test.client.store_rendered_templates', new=lambda *args, **kwargs: None)(test_class)
    original_setup = test_class.setUpClass.__func__

    def setUpClass(cls):
        os.makedirs(os.path.join(STATIC_ROOT, 'jsi18n', 'en'))
        with open(os.path.join(STATIC_ROOT, 'jsi18n', 'en', 'djangojs.js'), 'w'):
            pass
        cls.addClassCleanup(shutil.rmtree, STATIC_ROOT, ignore_errors=True)
        original_setup(cls)

    test_class.setUpClass = classmethod(setUpClass)
    return test_class


@renders_pages
@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ProblemDataViewTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        create_user(username='admin', is_superuser=True, is_staff=True)
        create_problem_type(name='type')
        cls.problem = create_problem(code='zipautoload', types=('type',))

    def setUp(self):
        self.client.force_login(create_user(username='admin', is_superuser=True, is_staff=True))
        self.url = reverse('problem_data', args=[self.problem.code])

    def _post(self, zip_bytes=None):
        data = {
            'problem-data-output_limit': '',
            'problem-data-output_prefix': '',
            'problem-data-checker': '',
            'problem-data-checker_args': '',
            'cases-TOTAL_FORMS': '0',
            'cases-INITIAL_FORMS': '0',
            'cases-MIN_NUM_FORMS': '0',
            'cases-MAX_NUM_FORMS': '1000',
        }
        if zip_bytes is not None:
            data['problem-data-zipfile'] = SimpleUploadedFile('data.zip', zip_bytes)
        return self.client.post(self.url, data, follow=True)

    def test_storage_uses_temp_media_root(self):
        self.assertEqual(problem_data_storage.location, MEDIA_ROOT)

    def test_yaml_zip_creates_cases_and_init(self):
        self._post(make_zip_bytes({'init.yml': ONE_CASE_INIT, '1.in': 'a', '1.out': 'b'}))
        self.assertEqual(ProblemTestCase.objects.filter(dataset=self.problem).count(), 1)
        self.assertTrue(problem_data_storage.exists('zipautoload/init.yml'))
        self.assertEqual(ProblemData.objects.get(problem=self.problem).feedback, '')

    def test_zip_without_yaml_registers_pairs_and_asks_for_points(self):
        self._post(make_zip_bytes({'1.in': 'a', '1.out': 'b'}))
        case = ProblemTestCase.objects.get(dataset=self.problem)
        self.assertIsNone(case.points)
        self.assertIn('Points must be defined', ProblemData.objects.get(problem=self.problem).feedback)

    def test_invalid_yaml_shows_error_and_keeps_cases(self):
        ProblemTestCase.objects.create(dataset=self.problem, order=1, input_file='old.in', output_file='old.out',
                                       points=5, is_pretest=False)
        self._post(make_zip_bytes({'init.yml': '- 1', 'old.in': 'a', 'old.out': 'b'}))
        case = ProblemTestCase.objects.get(dataset=self.problem)
        self.assertEqual((case.input_file, case.points), ('old.in', 5))
        data = ProblemData.objects.get(problem=self.problem)
        self.assertTrue(data.feedback)
        self.assertTrue(os.path.exists(data.zipfile.path))

    def test_invalid_yaml_feedback_keeps_the_compile_error(self):
        self._post(make_zip_bytes({'init.yml': ONE_CASE_INIT, '1.in': 'a', '1.out': 'b'}))
        self._post(make_zip_bytes({'init.yml': '- 1\n- 2\n'}))
        feedback = ProblemData.objects.get(problem=self.problem).feedback
        self.assertIn('init.yml must be a mapping.', feedback)
        self.assertIn('does not exist', feedback)

    def test_warnings_are_shown(self):
        response = self._post(make_zip_bytes({'1.in': 'a', '1.out': 'b', 'x.ans': 'c'}))
        self.assertContains(response, '1 file in the zip could not be paired as input and output and was ignored.')

    def test_post_without_zip_applies_nothing(self):
        self._post(make_zip_bytes({'init.yml': 'test_cases:\n- {in: 1.in, out: 1.out, points: 10}\n'
                                               '- {in: 2.in, out: 2.out, points: 10}\n',
                                   '1.in': 'a', '1.out': 'b', '2.in': 'a', '2.out': 'b'}))
        self.assertEqual(ProblemTestCase.objects.filter(dataset=self.problem).count(), 2)
        ProblemTestCase.objects.filter(dataset=self.problem, order=2).delete()
        self._post()
        self.assertEqual(ProblemTestCase.objects.filter(dataset=self.problem).count(), 1)

    def test_replacement_zip_replaces_stored_zip(self):
        self._post(make_zip_bytes({'1.in': 'first', '1.out': 'first'}))
        second = make_zip_bytes({'1.in': 'second', '1.out': 'second', '2.in': 'x', '2.out': 'y'})
        self._post(second)
        data = ProblemData.objects.get(problem=self.problem)
        self.assertTrue(data.zipfile)
        self.assertTrue(problem_data_storage.exists(data.zipfile.name))
        with open(data.zipfile.path, 'rb') as stored:
            self.assertEqual(stored.read(), second)


@renders_pages
class ProblemDataPageNoticesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_user(username='admin', is_superuser=True, is_staff=True)
        cls.author = create_user(username='author', user_permissions=['edit_own_problem'])
        create_problem_type(name='type')
        cls.problem = create_problem(code='noticeprob', types=('type',), authors=('author',))
        cls.url = reverse('problem_data', args=[cls.problem.code])
        cls.manage_url = reverse('problem_manage_submissions', args=[cls.problem.code])

    def test_page_has_help_and_rejudge_text(self):
        self.client.force_login(create_user(username='admin', is_superuser=True, is_staff=True))
        response = self.client.get(self.url)
        self.assertContains(response, 'id="data-help"')
        self.assertContains(response, 'id="rejudge-notice"')

    def test_rejudge_link_for_subs_manager(self):
        self.client.force_login(create_user(username='admin', is_superuser=True, is_staff=True))
        response = self.client.get(self.url)
        self.assertContains(response, 'id="rejudge-link"')
        self.assertContains(response, self.manage_url)

    def test_no_rejudge_link_without_permission(self):
        self.client.force_login(self.author)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="rejudge-notice"')
        self.assertNotContains(response, 'id="rejudge-link"')
