import unittest

from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestAIConfigurationMigration(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')

        with Transaction().start(
                config.database_name, config.user,
                context=config.context) as transaction:
            pool = Pool(config.database_name)
            AIModel = pool.get('ai.model')
            Configuration = pool.get('ai.configuration')
            model, = AIModel.create([{
                        'name': 'Migration model',
                        'model_name': 'example/model',
                        'provider': 'openrouter',
                        'type': 'llm',
                        }])
            transaction._locked_tables.add(Configuration._table)
            Configuration.create([{
                        'office_title_model': model.id,
                        'office_language_model': model.id,
                        }])

            handler = Configuration.__table_handler__('office')
            handler.column_rename(
                'office_title_model', 'brainbow_title_model')
            handler.column_rename(
                'office_language_model', 'brainbow_language_model')

            Configuration.__register__('office')

            migrated = Configuration(1)
            self.assertEqual(migrated.office_title_model, model)
            self.assertEqual(migrated.office_language_model, model)
            transaction.commit()
