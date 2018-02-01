# -*- coding: utf-8 -*-
import os
import sys
import uuid
import copy
import httplib
import unittest
import responses
import requests
import re
import jwt
from binascii import crc32

from driftconfig.util import set_sticky_config, get_default_drift_config
import driftconfig.testhelpers

import logging
log = logging.getLogger(__name__)

service_username = "user+pass:$SERVICE$"
service_password = "SERVICE"
local_password = "LOCAL"

big_number = 9999999999


def uuid_string():
    return str(uuid.uuid4()).split("-")[0]


def make_unique(name):
    """Make 'name' unique by appending random numbers to it."""
    return name + uuid_string()


db_name = None


def flushwrite(text):
    sys.stdout.write(text + '\n')
    sys.stdout.flush()


_tenant_is_set_up = False


def setup_tenant(config_size=None, use_app_config=True):
    """
    Called from individual test modules.
    create a tenant only if the test module was not called from
    the kitrun's systest command
    (in which case drift_test_database has been set in environ)
    Also configure some basic parameters in the app.

    TODO: Fix up app config. In the meantime:
    If 'use_app_config' is True, the tenant will be set up using
    app config from /config/config.json. If not, the tenant is set
    up using empty app config.

    Returns the table store object for the current config.
    """
    global _tenant_is_set_up
    if _tenant_is_set_up:
        return get_default_drift_config()

    _tenant_is_set_up = True

    # TODO: Fix this app config business
    from drift.flaskfactory import load_flask_config, set_sticky_app_config
    if use_app_config:
        app_config = load_flask_config()
    else:
        app_config = {'resources': [], 'resource_attributes': {}}
    set_sticky_app_config(app_config)

    # Create a test tenant, including the kitchen sink.
    ts = driftconfig.testhelpers.create_test_domain(
        config_size=config_size,
        resources=app_config['resources'],
        resource_attributes=app_config['resource_attributes'],
    )
    set_sticky_config(ts)

    # Pick any tier as the default tier then pick any tenant and deployable from that tier
    # as the default for each respectively.
    tier = ts.get_table('tiers').find()[0]
    tier_name = tier['tier_name']
    tenant = ts.get_table('tenants').find({'tier_name': tier_name})[0]
    deployable = ts.get_table('deployables').find({'tier_name': tier_name})[0]

    os.environ['DRIFT_TIER'] = tier_name
    os.environ['DRIFT_DEFAULT_TENANT'] = tenant['tenant_name']
    app_config['name'] = deployable['deployable_name']

    # mixamix
    app_config['TESTING'] = True

    return ts


def remove_tenant():
    """
    Called from individual test modules.
    """
    global _tenant_is_set_up
    if _tenant_is_set_up:
        from drift.flaskfactory import set_sticky_app_config
        set_sticky_app_config(None)
        set_sticky_config(None)
        _tenant_is_set_up = False


class DriftBaseTestCase(unittest.TestCase):
    headers = {}
    token = None
    current_user = {}
    endpoints = {}
    player_id = None
    user_id = None

    @staticmethod
    def mock(func):
        @responses.activate
        def wrapped(self, *args, **kwargs):
            self._setup_mocking()
            return func(self, *args, **kwargs)

        return wrapped

    def _do_request(self, method, endpoint, data=None,
                    params=None, *args, **kw):

        """
        Note that here we must use a inner function, otherwise mock
        will be evaluated at the module import time.
        """
        @DriftBaseTestCase.mock
        def inner(self, method, endpoint, data, params, *args, **kw):
            check = kw.pop("check", True)
            expected_status_code = kw.pop("expected_status_code", httplib.OK)
            headers = copy.copy(self.headers)
            if "Accept" not in headers:
                headers["Accept"] = "application/json"

            if data:
                headers["Content-Type"] = "application/json"
                if not isinstance(data, list) and not isinstance(data, dict):
                    raise Exception("Data must be a list or a dict: %s" % data)
            if db_name:
                headers["tenant"] = db_name

            if not endpoint.startswith(self.host):
                endpoint = self.host + endpoint

            r = getattr(requests, method)(
                endpoint,
                json=data,
                headers=headers,
                params=params

            )
            if check:
                self.assertEqual(
                    r.status_code, expected_status_code,
                    u"Status code should be {} but is {}: {}".format(
                        expected_status_code,
                        r.status_code, r.text.replace("\\n", "\n")
                    )
                )
            return r
        return inner(self, method, endpoint, data, params, *args, **kw)

    def _setup_mocking(self):
        def _mock_callback(request):
            method = request.method.lower()
            url = request.path_url
            handler = getattr(self.app, method)
            r = handler(
                url,
                data=request.body,
                headers=dict(request.headers)
            )
            return (r.status_code, r.headers, r.data)

        pattern = re.compile("{}/(.*)".format(self.host))
        methods = [
            responses.GET,
            responses.POST,
            responses.PUT,
            responses.DELETE,
            responses.PATCH,
        ]
        for method in methods:
            responses.add_callback(
                method, pattern,
                callback=_mock_callback
            )

    def get(self, *args, **kw):
        return self._do_request("get", *args, **kw)

    def put(self, *args, **kw):
        return self._do_request("put", *args, **kw)

    def post(self, *args, **kw):
        return self._do_request("post", *args, **kw)

    def delete(self, *args, **kw):
        return self._do_request("delete", *args, **kw)

    def patch(self, *args, **kw):
        return self._do_request("patch", *args, **kw)

    def setUp(self):
        pass

    def auth(self, username=None):
        """
        Do an auth call against the current app's /auth endpoint and fetch the
        root document which includes all user endpoints.
        """
        username = username or "systest"
        payload = {
            "provider": "unit_test",
            "username": username,
            "password": local_password,
        }
        resp = self.post("/auth", data=payload)

        self.token = resp.json()["token"]
        self.jti = resp.json()["jti"]
        self.current_user = jwt.decode(self.token, verify=False)
        self.player_id = self.current_user["player_id"]
        self.user_id = self.current_user["user_id"]
        self.headers = {"Authorization": "JWT " + self.token}

        r = self.get("/")
        self.endpoints = r.json()["endpoints"]

    def auth_service(self):
        """
        Authenticate as a service user
        """
        payload = {
            "username": service_username,
            "password": service_password,
            "provider": "user+pass"
        }
        resp = self.post("/auth", data=payload)
        token = resp.json()["token"]
        jti = resp.json()["jti"]
        self.token = token
        self.jti = jti
        self.current_user = jwt.decode(self.token, verify=False)
        self.player_id = self.current_user["player_id"]
        self.user_id = self.current_user["user_id"]
        self.headers = {"Authorization": "JWT " + token, }

        r = self.get("/")
        self.endpoints = r.json()["endpoints"]

    @classmethod
    def setUpClass(cls):
        setup_tenant()
        cls.host = "http://localhost"
        from appmodule import app
        cls.app = app.test_client()

        import driftbase.auth.authenticate
        if driftbase.auth.authenticate.authenticate is None:
            driftbase.auth.authenticate.authenticate = _authenticate_mock

    @classmethod
    def tearDownClass(cls):
        remove_tenant()

        import driftbase.auth.authenticate
        if driftbase.auth.authenticate.authenticate is _authenticate_mock:
            driftbase.auth.authenticate.authenticate = None


def _authenticate_mock(username, password, automatic_account_creation=True):
    ret = {
        'user_name': username,
        'identity_id': username,
        'user_id': crc32(username),
        'player_id': crc32(username),
        'roles': ['service'] if username == service_username else [],
    }

    return ret
