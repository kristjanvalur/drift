#
import json

from flask import Flask
from unittest import TestCase
from drift.flaskfactory import _apply_patches


class DriftTestCase(TestCase):

    def __call__(self, result=None):
        """
        Does the required setup, doing it here
        means you don't have to call super.setUp
        in subclasses.
        """
        try:
            self._pre_setup()
            super(DriftTestCase, self).__call__(result)
        finally:
            self._post_teardown()

    def _pre_setup(self):
        self.app = self.create_app()
        self.client = self.app.test_client()

        self._ctx = self.app.test_request_context()
        self._ctx.push()

    def _post_teardown(self):
        if getattr(self, '_ctx', None) is not None:
            self._ctx.pop()
            del self._ctx

        if getattr(self, 'app', None) is not None:
            if getattr(self, '_orig_response_class', None) is not None:
                self.app.response_class = self._orig_response_class
            del self.app

        if hasattr(self, 'client'):
            del self.client

        if hasattr(self, 'templates'):
            del self.templates

        if hasattr(self, 'flashed_messages'):
            del self.flashed_messages

    def create_app(self):
        app = Flask(__name__)
        # apply the same kind of patching as regular factory apps get
        _apply_patches(app)
        app.config['TESTING'] = True
        self.test_client = app.test_client()
        app.config["name"] = '{} unit test'.format(self.__class__.__name__)
        self.headers = [('Accept', 'application/json')]
        return app

    def get(self, expected_code, path, **kw):
        kw['path'] = path
        kw['headers'] = self.headers
        response = self.client.get(**kw)
        return self.assert_response(response, expected_code)

    def post(self, expected_code, path, data, **kw):
        kw['path'] = path
        kw['headers'] = self.headers
        kw['data'] = json.dumps(data)
        kw['content_type'] = 'application/json'
        response = self.client.post(**kw)
        return self.assert_response(response, expected_code)

    def delete(self, expected_code, path, **kw):
        kw['path'] = path
        kw['headers'] = self.headers
        response = self.client.delete(**kw)
        return self.assert_response(response, expected_code)

    def assert_response(self, response, expected_code):
        if response.status_code != expected_code:
            if response.headers['Content-Type'] == 'application/json':
                description = json.loads(response.data).get('description', response.data)
            else:
                description = response.data
            self.assertStatus(response, expected_code, description)
        return response
