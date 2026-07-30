from django.test import TestCase

from judge.models.tests.util import create_problem, create_problem_type, create_user


class ProblemDataModelTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_user(username='author')
        create_problem_type(name='type')
        cls.problem = create_problem(code='checkerprob', types=('type',), authors=('author',))

    def test_checker_file_field_exists_and_defaults_empty(self):
        from judge.models import ProblemData
        data = ProblemData.objects.create(problem=self.problem)
        self.assertFalse(data.checker_file)

    def test_update_code_relocates_checker_file(self):
        from judge.models import ProblemData
        data = ProblemData.objects.create(problem=self.problem)
        data.checker_file.name = 'checkerprob/checker.py'
        data.save()

        data._update_code('checkerprob', 'renamedprob')

        self.assertEqual(data.checker_file.name, 'renamedprob/checker.py')
