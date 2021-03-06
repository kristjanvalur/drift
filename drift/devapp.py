# -*- coding: utf-8 -*-
import logging
import os

from .flaskfactory import drift_app

logging.basicConfig(level='INFO')

# Default tenant for devapp is 'developer'
tenant_name = os.environ.setdefault('DRIFT_DEFAULT_TENANT', 'developer')
logging.getLogger(__name__).info("Default tenant for this developer app is '%s'.", tenant_name)
app = drift_app()
