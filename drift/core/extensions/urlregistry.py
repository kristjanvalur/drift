# -*- coding: utf-8 -*-

# store endpoints at import time here.  Register them with
# the app when done.
_registered_endpoints = set()


class EndpointRegistry(object):

    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.app = app
            self._init_app()

    def _init_app(self):
        if not hasattr(self.app, 'extensions'):
            self.app.extensions = {}
        self.app.extensions['urlregistry'] = self
        self.app.endpoint_registry_funcs = []

    def register_endpoints(self, f):
        self.app.endpoint_registry_funcs.append(f)
        return f


def register_endpoints(f):
    # This is called at import time, at which point we do not have any single
    # app object. Since it is done at import, it is a global state.  Store
    # that here and apply it later.
    _registered_endpoints.add(f)
    return f


def register_extension(app):
    registry = EndpointRegistry(app)
    return registry


def finalize_extension(app):
    """
    Once everything has registered their extensions at import time, we can
    apply it to the app module.
    """
    registry = app.extensions['urlregistry']
    for f in _registered_endpoints:
        registry.register_endpoints(f)
