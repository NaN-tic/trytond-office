import unittest
from xml.etree import ElementTree

from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestGalateaAttachmentForm(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules(['office', 'galatea'])

        with Transaction().start(
                config.database_name, config.user,
                context=config.context):
            ModelData = config.pool.get('ir.model.data')
            Attachment = config.pool.get('ir.attachment')
            view = Attachment.fields_view_get(
                view_id=ModelData.get_id('office', 'view_attachment_form'),
                view_type='form')
            tree_view = Attachment.fields_view_get(
                view_id=ModelData.get_id('office', 'view_attachment_list'),
                view_type='tree')

        arch = ElementTree.fromstring(view['arch'])
        checkboxes = arch.find("./group[@id='checkboxes']")
        self.assertIsNotNone(checkboxes)
        self.assertIsNotNone(
            checkboxes.find("./field[@name='allow_galatea']"))
        tree_arch = ElementTree.fromstring(tree_view['arch'])
        self.assertIsNotNone(
            tree_arch.find("./field[@name='allow_galatea']"))
