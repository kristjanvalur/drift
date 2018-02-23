# -*- coding: utf-8 -*-
from __future__ import absolute_import
import os
import os.path
import importlib
from contextlib import contextmanager
import socket
import getpass
import httplib

from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from alembic.config import Config
from alembic import command

from werkzeug.local import LocalProxy
from sqlalchemy import create_engine
from flask import g, abort
from flask import _app_ctx_stack as stack

from drift.flaskfactory import load_flask_config

import logging
log = logging.getLogger(__name__)


# defaults when making a new tier
TIER_DEFAULTS = {
    "server": "<PLEASE FILL IN>",
    "database": None,
    "port": 5432,
    "username": "zzp_user",
    "password": "zzp_user",
    "driver": "postgresql",
}


def register_deployable(ts, deployablename, attributes):
    """
    Deployable registration callback.
    'deployablename' is from table 'deployable-names'.
    """
    # Make sure 'models' is specified in attributes
    if 'models' not in attributes:
        raise RuntimeError('''
'models' is a required attribute for postgres resource.
Add to config.json the name of the modules containing your SQLAlchemy db models.
Example:

    "resource_attributes": {
            "drift.core.resources.postgres": {
                "models": ["%s.db.models"]
            }
    }
    ''' % deployablename['deployable_name'].replace('-', ''))


def register_resource_on_tier(ts, tier, attributes):
    """
    Tier registration callback.
    'tier' is from table 'tiers'.
    'attributes' is a dict containing optional attributes for default values.
    """
    pass


def register_deployable_on_tier(ts, deployable, attributes):
    """
    Deployable registration callback.
    'deployable' is from table 'deployables'.
    """
    # Add default parameters for Postgres connection if needed.
    pass


def provision_resource(ts, tenant_config, attributes):
    """
    Create, recreate or delete resources for a tenant.
    'tenant_config' is a row from 'tenants' table for the particular tenant, tier and deployable.
    LEGACY SUPPORT: 'attributes' points to the current resource attributes within 'tenant_config'.
    """

    # Create the tier default user on the DBMS and assign "can login" privilege
    # and add role "rds_superuser".
    params = process_connection_values(attributes)
    params["username"] = MASTER_USER
    params["password"] = MASTER_PASSWORD
    params["database"] = MASTER_DB
    engine = connect(params)
    params['role'] = 'rds_superuser'
    sql = "CREATE ROLE zzp_user PASSWORD '{password}';".format(**params)
    try:
        engine.execute(sql)
    except Exception as e:
        if "already exists" not in str(e):
            raise

    sql = "GRANT {role} TO zzp_user;".format(**params)
    try:
        engine.execute(sql)
    except Exception as e:
        if "role \"{role}\" does not exist".format(**params) not in str(e):
            raise

    report = []

    # LEGACY SUPPORT:
    # The old provision logic would load in config.json on its own to get the app name. Now we simply
    # inject this info into the attributes/params dict.
    attributes['application_name'] = tenant_config['deployable_name']

    # MORE LEGACY STUFF:
    # The db model module names are registered in 'deployable-names' table. We inject this info into
    # the attributes/params dict.
    depl = ts.get_table('deployable-names').get({'deployable_name': tenant_config['deployable_name']})
    attributes['models'] = depl['resource_attributes']['drift.core.resources.postgres']['models']

    if os.environ.get('DRIFT_USE_LOCAL_SERVERS', False):
            # Override 'server'
            attributes['server'] = 'localhost'

    # Initialize the DB name if applicable
    if not attributes.get('database'):
        attributes["database"] = "{}.{}".format(
            tenant_config['tenant_name'], tenant_config['deployable_name'])

    if tenant_config['state'] == 'initializing':
        # Create or recreate db
        if db_exists(attributes.copy()):
            drop_db(attributes.copy(), force=True)
            report.append("Database for tenant already existed, dropped the old DB.")
        create_db(attributes.copy())
        report.append("Created a new DB: {}".format(format_connection_string(attributes.copy())))
    elif tenant_config['state'] == 'active':
        if not db_exists(attributes.copy()):
            log.warning(
                "Database for tenant '%s' doesn't exist, which is unexpected. Creating one now.",
                tenant_config['tenant_name']
            )
            create_db(attributes.copy())
            report.append("Database didn't exist, which was unexpected, so a new DB was created: {}".format(
                format_connection_string(attributes.copy())))
        report.append("Database check successfull for DB: {}".format(format_connection_string(attributes.copy())))
    elif tenant_config['state'] == 'uninitializing':
        # Archive or delete db
        pass

    return report



# we need a single master db on all db instances to perform db maintenance
MASTER_DB = 'postgres'
MASTER_USER = 'postgres'
MASTER_PASSWORD = 'postgres'
ECHO_SQL = False
SCHEMAS = ["public"]


class Postgres(object):
    """Postgres Flask extension."""

    application_name = None  # Set just in time to something sensible (see below)

    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        if not hasattr(app, 'extensions'):
            app.extensions = {}

        app.extensions['postgres'] = self
        app.before_request(self.before_request)
        app.teardown_request(self.teardown_request)

    def before_request(self):
        # Add a just-in-time getter for session
        g.db = LocalProxy(self.get_session)

    def teardown_request(self, exception):
        """Return the database connection at the end of the request"""
        ctx = stack.top
        if ctx is not None:
            if hasattr(ctx, 'sqlalchemy_session'):
                try:
                    ctx.sqlalchemy_session.close()
                except Exception as e:
                    log.error("Could not close sqlalchemy session: %s", e)

    def get_session(self):
        ctx = stack.top
        if ctx is not None:
            if not hasattr(ctx, 'sqlalchemy_session'):
                ctx.sqlalchemy_session = get_sqlalchemy_session()
            return ctx.sqlalchemy_session

    @classmethod
    def get_application_name(cls):

        if cls.application_name is None:
            # Pretty print a nice name for this connection, just in time.
            cls.application_name = '{}:{}@{}'.format(
                load_flask_config()['name'],
                getpass.getuser(),
                socket.gethostname().split(".")[0],
            )

        return cls.application_name


def register_extension(app):
    Postgres(app)


def get_sqlalchemy_session(conn_string=None):
    """
    Return an SQLAlchemy session for the specified DB connection string
    """
    if not conn_string:
        if not g.conf.tenant:
            abort(httplib.BAD_REQUEST, "No DB resource available because no tenant is specified.")

        ci = g.conf.tenant.get('postgres')
        conn_string = format_connection_string(ci)

    log.debug("Creating sqlalchemy session with connection string '%s'", conn_string)
    connect_args = {
        'connect_timeout': 10,
        'application_name': Postgres.get_application_name(),
    }
    engine = create_engine(conn_string, connect_args=connect_args, echo=False, poolclass=NullPool)
    session_factory = sessionmaker(bind=engine, expire_on_commit=True)
    session = session_factory()
    session.expire_on_commit = False
    return session


@contextmanager
def sqlalchemy_session(conn_string=None):
    session = get_sqlalchemy_session(conn_string)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def process_connection_values(postgres_parameters):
    """
    Returns a copy of 'postgres_parameters' where values have been
    processed or or overridden if applicable.
    """
    postgres_parameters = postgres_parameters.copy()
    if os.environ.get('DRIFT_USE_LOCAL_SERVERS', False):
        # Override 'server'
        postgres_parameters['server'] = 'localhost'
    return postgres_parameters


def format_connection_string(postgres_parameters):
    postgres_parameters = process_connection_values(postgres_parameters)
    connection_string = '{driver}://{username}:{password}@{server}:{port}/{database}'.format(**postgres_parameters)
    return connection_string


def connect(params, connect_timeout=None):

    engine = create_engine(
        format_connection_string(params),
        echo=ECHO_SQL,
        isolation_level='AUTOCOMMIT',
        connect_args={
            'connect_timeout': connect_timeout or 10,
            'application_name': params.get('application_name', 'drift.core.resources.postgres'),
        }
    )
    return engine


def db_exists(params):
    try:
        engine = connect(params)
        engine.execute("SELECT 1=1")
    except Exception as e:
        if "does not exist" in repr(e):
            return False
        else:
            print "OOPS:", e
            return False
    return True


def db_check(params):
    """
    Do a simple check on DB referenced by 'params' and return a string describing any error
    that may occur. If all is fine, None is returned.
    """
    try:
        engine = connect(params, connect_timeout=2)
        engine.execute("SELECT 1=1")
    except Exception as e:
        return str(e)


def create_db(params):
    params = process_connection_values(params)
    db_name = params["database"]
    username = params["username"]

    params["username"] = MASTER_USER
    params["password"] = MASTER_PASSWORD

    master_params = params.copy()
    master_params["database"] = MASTER_DB
    engine = connect(master_params)
    engine.execute('COMMIT')
    sql = 'CREATE DATABASE "{}";'.format(db_name)
    try:
        engine.execute(sql)
    except Exception as e:
        print sql, e

    # TODO: This will only run for the first time and fail in all other cases.
    # Maybe test before instead?
    sql = 'CREATE ROLE {user} LOGIN PASSWORD "{user}" VALID UNTIL "infinity";'.format(user=username)
    try:
        engine.execute(sql)
    except Exception as e:
        pass

    engine = connect(params)

    # TODO: Alembic (and sqlalchemy for that matter) don't like schemas. We should
    # figure out a way to add these later
    # LEGACY SUPPORT: We can't load config.json arbitrarily here so instead we just assume
    # db model modules are found in "<flugger>"
    models = params.get("models", [])
    if not models:
        raise Exception("This app has no models defined in config")

    for model_module_name in models:
        log.info("Building models from %s", model_module_name)
        models = importlib.import_module(model_module_name)
        models.ModelBase.metadata.create_all(engine)
        if hasattr(models, 'on_create_db'):
            models.on_create_db(engine)

    # stamp the db with the latest alembic upgrade version
    alembic_not_supported = True
    if alembic_not_supported:
        log.warning("NOTE! Alembic not supported at the moment. No db upgrades are run.")
    else:
        from drift.flaskfactory import _find_app_root
        approot = _find_app_root()
        ini_path = os.path.join(approot, "alembic.ini")
        alembic_cfg = Config(ini_path)
        script_path = os.path.join(os.path.split(os.path.abspath(ini_path))[0], "alembic")
        alembic_cfg.set_main_option("script_location", script_path)
        db_names = alembic_cfg.get_main_option('databases')
        connection_string = format_connection_string(params)
        alembic_cfg.set_section_option(db_names, "sqlalchemy.url", connection_string)
        command.stamp(alembic_cfg, "head")

    for schema in SCHEMAS:
        # Note that this does not automatically grant on tables added later
        sql = '''
                 GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO {user};
                 GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA "{schema}" TO {user};
                 GRANT ALL ON SCHEMA "{schema}" TO {user};'''.format(schema=schema, user=username)
        try:
            engine.execute(sql)
        except Exception as e:
            print sql, e

    return db_name


def drop_db(_params, force=False):

    params = process_connection_values(_params)
    db_name = params["database"]
    if 'test' not in db_name.lower() and not force:
        raise RuntimeError("Will not drop database '{}' because it's not a test DB. Use 'force' to override".format(db_name))

    params["database"] = MASTER_DB
    params["username"] = MASTER_USER
    params["password"] = MASTER_PASSWORD

    if not db_exists(params):
        print "Not dropping database '{}' as it doesn't seem to exist.".format(db_name)
        return

    engine = connect(params)

    # disconnect connected clients
    engine.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{}';"
                   .format(db_name))

    sql = 'DROP DATABASE "{}";'.format(db_name)
    engine.execute('COMMIT')

    try:
        engine.execute(sql)
    except Exception as e:
        print sql, e

    log.info("Database '%s' has been dropped on '%s'", db_name, params["server"])


def healthcheck():
    if "postgres" not in g.conf.tenant:
        abort(httplib.SERVICE_UNAVAILABLE, "Tenant config does not have 'postgres' section.")
    for k in TIER_DEFAULTS.keys():
        if not g.conf.tenant["postgres"].get(k):
            abort(httplib.SERVICE_UNAVAILABLE, "'postgres' config missing key '%s'" % k)

    rows = g.db.execute("SELECT 1+1")
    rows.fetchall()[0]
