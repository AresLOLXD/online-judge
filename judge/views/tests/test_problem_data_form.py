from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from judge.models import ProblemData
from judge.models.tests.util import create_problem, create_problem_type, create_user
from judge.views.problem_data import ProblemDataForm


class ProblemDataFormTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_user(username='author')
        create_problem_type(name='type')
        cls.problem = create_problem(code='formcheckerprob', types=('type',), authors=('author',))

    def _base_post_data(self, checker=''):
        return {
            'problem-data-output_limit': '',
            'problem-data-output_prefix': '',
            'problem-data-checker': checker,
            'problem-data-checker_args': '',
        }

    def test_custom_checker_without_file_is_invalid(self):
        instance = ProblemData.objects.create(problem=self.problem)
        form = ProblemDataForm(data=self._base_post_data(checker='custom'), files={}, prefix='problem-data',
                               instance=instance)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_custom_checker_with_clean_file_is_valid(self):
        instance = ProblemData.objects.create(problem=self.problem)
        checker_file = SimpleUploadedFile('checker.py', b"""
def check(process_output, judge_output, **kwargs):
    return process_output == judge_output
""")
        files = {'problem-data-checker_file': checker_file}
        form = ProblemDataForm(data=self._base_post_data(checker='custom'), files=files, prefix='problem-data',
                               instance=instance)
        self.assertTrue(form.is_valid(), form.errors)

    def test_custom_checker_with_dangerous_file_is_rejected(self):
        instance = ProblemData.objects.create(problem=self.problem)
        checker_file = SimpleUploadedFile('checker.py', b"""
import subprocess

def check(process_output, judge_output, **kwargs):
    return True
""")
        files = {'problem-data-checker_file': checker_file}
        form = ProblemDataForm(data=self._base_post_data(checker='custom'), files=files, prefix='problem-data',
                               instance=instance)
        self.assertFalse(form.is_valid())
        self.assertIn('checker_file', form.errors)
        self.assertIn('subprocess', form.errors['checker_file'][0])

    def test_non_custom_checker_ignores_uploaded_file_requirement(self):
        instance = ProblemData.objects.create(problem=self.problem)
        form = ProblemDataForm(data=self._base_post_data(checker='standard'), files={}, prefix='problem-data',
                               instance=instance)
        self.assertTrue(form.is_valid(), form.errors)

    def test_checker_file_must_be_python(self):
        instance = ProblemData.objects.create(problem=self.problem)
        checker_file = SimpleUploadedFile('checker.txt', b'not python')
        files = {'problem-data-checker_file': checker_file}
        form = ProblemDataForm(data=self._base_post_data(checker='custom'), files=files, prefix='problem-data',
                               instance=instance)
        self.assertFalse(form.is_valid())
        self.assertIn('checker_file', form.errors)

    def test_non_custom_checker_clears_uploaded_file(self):
        instance = ProblemData.objects.create(problem=self.problem)
        checker_file = SimpleUploadedFile('checker.py', b"""
def check(process_output, judge_output, **kwargs):
    return process_output == judge_output
""")
        files = {'problem-data-checker_file': checker_file}
        form = ProblemDataForm(data=self._base_post_data(checker='standard'), files=files, prefix='problem-data',
                               instance=instance)
        self.assertTrue(form.is_valid(), form.errors)
        data = form.save()
        self.assertFalse(data.checker_file)

    def test_non_custom_checker_clears_existing_file(self):
        instance = ProblemData.objects.create(problem=self.problem, checker='custom')
        instance.checker_file.save('checker.py', SimpleUploadedFile('checker.py', b"""
def check(process_output, judge_output, **kwargs):
    return process_output == judge_output
"""), save=True)

        form = ProblemDataForm(data=self._base_post_data(checker='standard'), files={}, prefix='problem-data',
                               instance=instance)
        self.assertTrue(form.is_valid(), form.errors)
        data = form.save()
        self.assertFalse(data.checker_file)
