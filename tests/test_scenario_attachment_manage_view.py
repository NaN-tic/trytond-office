import unittest
from xml.etree import ElementTree

from proteus import Model
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestAttachmentManageView(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')
        Action = Model.get('ir.action.act_window', config=config)
        action, = Action.find([
                ('res_model', '=', 'ir.attachment'),
                ('name', '=', 'Documents & Attachments'),
                ])
        menu_view = min(action.act_window_views, key=lambda v: v.sequence).view

        with Transaction().start(
                config.database_name, config.user, context=config.context):
            Attachment = config.pool.get('ir.attachment')
            ModelData = config.pool.get('ir.model.data')
            manage = Attachment.fields_view_get(view_type='tree')
            self.assertEqual(manage['view_id'], ModelData.get_id(
                    'ir', 'attachment_view_tree'))
            arch = ElementTree.fromstring(manage['arch'])
            self.assertEqual(arch.get('editable'), '1')
            self.assertIsNotNone(arch.find("./field[@name='data']"))
            self.assertIsNotNone(arch.find("./field[@name='link']"))
            self.assertIsNotNone(arch.find(
                    "./button[@name='create_from_template']"))

            self.assertEqual(menu_view.id, ModelData.get_id(
                    'office', 'view_attachment_list'))
            menu = Attachment.fields_view_get(
                view_id=menu_view.id, view_type='tree')
            arch = ElementTree.fromstring(menu['arch'])
            self.assertIsNone(arch.get('editable'))
