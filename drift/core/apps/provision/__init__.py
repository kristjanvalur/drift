# -*- coding: utf-8 -*-
"""
Schames listing APIs
"""
import logging
import importlib
import httplib

from flask import Blueprint, current_app, url_for, abort, request, g
from flask_restful import Api, Resource, abort

from drift.configsetup import get_current_config
from driftconfig.relib import create_backend, get_store_from_url
from drift.core.extensions.jwt import jwt_not_required

from drift.auth.jwtchecker import requires_roles
from drift.core.extensions.schemachecker import simple_schema_request

log = logging.getLogger(__name__)
bp = Blueprint("admin", __name__)
api = Api(bp)

class AdminProvisionAPI(Resource):

    no_jwt_check = ["POST"]

    #@requires_roles("service")
    @simple_schema_request({
        "provisioners": {"type": "array", },
    }, required=[])
    def post(self):
        tenant_name = g.conf.tenant_name['tenant_name']
        tier_name = g.conf.tier['tier_name']

        # quick check for tenant state before downloading config
        if g.conf.tenant["state"] != "initializing":
            abort(httplib.BAD_REQUEST, message="You can only provision tenants which are in state 'initializing'. Tenant '%s' is in state '%s'" % (tenant_name, g.conf.tenant["state"]))

        args_per_provisioner = {}
        if request.json:
            for arg in request.json.get("provisioners", {}):
                if "provisioner" not in arg or "arguments" not in arg:
                    log.warning("Provisioner argument missing 'provisioner' or 'arguments'")
                    continue
                args_per_provisioner[arg["provisioner"]] = arg["arguments"]

        origin = g.conf.domain['origin']
        ts = get_store_from_url(origin)
        conf = get_current_config(ts, tenant_name=tenant_name)

        if conf.tenant["state"] != "initializing":
            raise RuntimeError("Tenant unexpectedly found in state '%s': %s" % (conf.tenant["state"], conf.tenant))

        resources = current_app.config.get("resources")
        for module_name in resources:
            m = importlib.import_module(module_name)
            if hasattr(m, "provision"):
                provisioner_name = m.__name__.split('.')[-1]
                log.info("Provisioning '%s' for tenant '%s' on tier '%s'", provisioner_name, tenant_name, tier_name)

                args = args_per_provisioner.get(provisioner_name, {})
                m.provision(conf, args)

        # Mark the tenant as ready
        conf.tenant["state"] = "active"

        # Save out config
        log.info("Saving config to %s", origin)
        origin_backend = create_backend(origin)
        ts.save_to_backend(origin_backend)

        local_origin = 'file://~/.drift/config/' + g.conf.domain['domain_name']
        log.info("Saving config to %s", local_origin)
        local_store = create_backend(local_origin)
        ts.save_to_backend(local_store)

        # invalidate flask config
        current_app.extensions['relib'].refresh()

        return "OK"


api.add_resource(AdminProvisionAPI, "/provision")