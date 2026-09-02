# This file is part office module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.tests.test_tryton import ModuleTestCase


class OfficeTestCase(ModuleTestCase):
    'Test Office module'
    module = 'office'
    extras = ['galatea']

del ModuleTestCase
