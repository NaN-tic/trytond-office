import unittest
from xml.etree import ElementTree

from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestAttachmentManageWopiView(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules(['office', 'wopi'])

        with Transaction().start(
                config.database_name, config.user, context=config.context):
            Attachment = config.pool.get('ir.attachment')
            ModelData = config.pool.get('ir.model.data')
            manage = Attachment.fields_view_get(view_type='tree')
            arch = ElementTree.fromstring(manage['arch'])
            self.assertEqual(arch.get('editable'), '1')
            self.assertIsNotNone(arch.find(
                    "./button[@name='create_from_template']"))
            self.assertIsNotNone(arch.find("./button[@name='open']"))
            self.assertIn('office_url', manage['fields'])

            menu = Attachment.fields_view_get(
                view_id=ModelData.get_id('office', 'view_attachment_list'),
                view_type='tree')
            arch = ElementTree.fromstring(menu['arch'])
            self.assertIsNone(arch.get('editable'))
            self.assertIsNotNone(arch.find("./button[@name='open']"))
