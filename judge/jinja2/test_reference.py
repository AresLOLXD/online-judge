from django.test import SimpleTestCase

from .reference import absolute_links

PAGE_URL = 'https://judge.example.com/problem/aplusb/pdf'


class AbsoluteLinksTest(SimpleTestCase):
    def absolutify(self, text):
        return absolute_links(text, PAGE_URL)

    def test_relative_anchor_href_becomes_absolute(self):
        tree = self.absolutify('<p><a href="/about/">About</a></p>')
        self.assertEqual(tree.xpath('.//a')[0].get('href'), 'https://judge.example.com/about/')

    def test_relative_image_src_becomes_absolute(self):
        tree = self.absolutify('<p><img src="/media/martor/image.png" alt="image"></p>')
        self.assertEqual(tree.xpath('.//img')[0].get('src'), 'https://judge.example.com/media/martor/image.png')

    def test_absolute_image_src_is_unchanged(self):
        tree = self.absolutify('<p><img src="https://cdn.example.org/image.png" alt="image"></p>')
        self.assertEqual(tree.xpath('.//img')[0].get('src'), 'https://cdn.example.org/image.png')

    def test_data_image_src_is_unchanged(self):
        src = 'data:image/png;base64,iVBORw0KGgo='
        tree = self.absolutify('<p><img src="%s" alt="image"></p>' % src)
        self.assertEqual(tree.xpath('.//img')[0].get('src'), src)
