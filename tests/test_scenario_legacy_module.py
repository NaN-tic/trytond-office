import unittest

from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestLegacyModule(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('brainbow')

        with Transaction().start(
                config.database_name, config.user,
                context=config.context):
            Module = Pool(config.database_name).get('ir.module')
            office, = Module.search([('name', '=', 'office')])
            legacy, = Module.search([('name', '=', 'brainbow')])

            self.assertEqual(office.state, 'activated')
            self.assertEqual(legacy.state, 'not activated')
