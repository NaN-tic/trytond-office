import unittest
from xml.etree import ElementTree

from proteus import Model
from trytond.pyson import PYSONDecoder
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestTextAttachment(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')
        Attachment = Model.get('ir.attachment', config=config)
        Group = Model.get('res.group', config=config)
        Lang = Model.get('ir.lang', config=config)
        Category = Model.get('office.category', config=config)

        with Transaction().start(
                config.database_name, config.user,
                context=config.context):
            AttachmentModel = config.pool.get('ir.attachment')
            ModelData = config.pool.get('ir.model.data')
            definitions = AttachmentModel.fields_get([
                    'description', 'language'])
            states = definitions['description']['states']
            self.assertTrue(
                PYSONDecoder({'type': 'text'}).decode(states)['invisible'])
            self.assertFalse(
                PYSONDecoder({'type': 'data'}).decode(states)['invisible'])
            states = definitions['language']['states']
            self.assertFalse(
                PYSONDecoder({'type': 'text'}).decode(states)['invisible'])
            self.assertFalse(
                PYSONDecoder({'type': 'data'}).decode(states)['invisible'])
            self.assertTrue(
                PYSONDecoder({'type': 'link'}).decode(states)['invisible'])

            view = AttachmentModel.fields_view_get(
                view_id=ModelData.get_id('office', 'view_attachment_form'),
                view_type='form')
            arch = ElementTree.fromstring(view['arch'])
            notebook = arch.find('./notebook')
            self.assertIsNotNone(notebook)
            self.assertIsNotNone(notebook.find(
                    "./page[@name='description']/field[@name='description']"))

        language, = Lang.find([('code', '=', 'en')])
        group = Group(name='Readers')
        group.save()
        category = Category(name='Manual')
        category.save()

        with config.set_context(default_unlinked=True):
            attachment = Attachment(
                name='Guide', type='text', content='Original text',
                language=language)
            attachment.categories.append(category)
            attachment.reader_groups.append(group)
            attachment.save()

        self.assertTrue(attachment.unlinked)
        self.assertEqual(
            attachment.resource.__class__.__name__, 'office.unlinked')
        self.assertEqual(attachment.content, 'Original text')
        self.assertEqual([item.id for item in attachment.categories], [category.id])
        self.assertEqual(
            [item.id for item in attachment.reader_groups], [group.id])

        attachment.data = b'This must not replace the text'
        attachment.save()
        attachment.reload()
        self.assertEqual(attachment.content, 'Original text')

        attachment_id = attachment.id
        Attachment.delete([attachment])
        with config.set_context(active_test=False):
            inactive = Attachment(attachment_id)
            self.assertFalse(inactive.active)
            Attachment.delete([inactive])
            self.assertFalse(Attachment.find([('id', '=', attachment_id)]))
