from io import BytesIO
import unittest
from zipfile import ZipFile

from proteus import Model, Wizard
from trytond.model.modelstorage import AccessError
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules, set_user


class TestDocumentTemplate(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')
        Attachment = Model.get('ir.attachment', config=config)
        Category = Model.get('office.category', config=config)
        Configuration = Model.get('office.configuration', config=config)
        Template = Model.get('office.document.template', config=config)
        User = Model.get('res.user', config=config)

        members = {
            'docx': 'word/document.xml',
            'xlsx': 'xl/worksheets/sheet1.xml',
            'pptx': 'ppt/presentation.xml',
            }
        templates = Template.find([
                ('extension', 'in', list(members)),
                ])
        self.assertEqual(
            {template.extension for template in templates}, set(members))
        for template in templates:
            self.assertTrue(template.active)
            self.assertEqual(template.type, 'data')
            data = bytes(template.data)
            self.assertLess(len(data), 2048)
            with ZipFile(BytesIO(data)) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn(members[template.extension], archive.namelist())
            template.active = False
            template.save()
        self.assertFalse(Template.find([]))
        with config.set_context(active_test=False):
            self.assertEqual(
                {template.extension for template in Template.find([])},
                set(members))

        configuration = Configuration(1)
        self.assertEqual(configuration.default_filename, 'unnamed document')
        configuration.default_filename = 'new-document'
        configuration.save()

        attachment = Attachment(
            name='uploaded.odt', type='data', data=b'Document')
        attachment.name = None
        attachment.data = None
        self.assertEqual(attachment.name, 'new-document')

        category = Category(name='Contracts')
        category.save()
        text_template = Template(
            name='Minutes', type='text', content='# Minutes')
        text_template.extension = '.MD'
        self.assertEqual(text_template.extension, 'md')
        self.assertEqual(text_template.mime_type, 'text/markdown')
        text_template.save()

        wizard = Wizard('office.document.create', config=config)
        self.assertTrue(wizard.form.unlinked)
        self.assertEqual(wizard.form.template, text_template)
        self.assertEqual(wizard.form.filename, 'new-document.md')
        wizard.form.filename = 'meeting.notes'
        wizard.form.template = text_template
        wizard.form.categories.append(category)
        wizard.execute('create_')

        attachment, = Attachment.find([('name', '=', 'meeting.md')])
        self.assertEqual(attachment.type, 'text')
        self.assertEqual(attachment.content, '# Minutes')
        self.assertEqual(attachment.mimetype, 'text/markdown')
        self.assertTrue(attachment.unlinked)
        self.assertEqual(
            [item.id for item in attachment.categories], [category.id])
        self.assertEqual(wizard.actions[0][0].id, attachment.id)

        data_template = Template(
            name='Letter', type='data',
            mime_type='application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.document', extension='docx', data=b'DOCX')
        data_template.save()
        empty = Attachment(
            name='draft.txt', type='data', unlinked=True)
        empty.save()

        wizard = Wizard('office.document.create', [empty], config=config)
        self.assertEqual(wizard.form.filename, 'draft.txt')
        self.assertTrue(wizard.form.unlinked)
        wizard.form.template = data_template
        self.assertEqual(wizard.form.filename, 'draft.docx')
        wizard.execute('create_')

        empty.reload()
        self.assertEqual(empty.name, 'draft.docx')
        self.assertEqual(bytes(empty.data), b'DOCX')
        self.assertEqual(empty.type, 'data')
        self.assertEqual(wizard.actions, [])

        link_template = Template(
            name='Portal', type='link', mime_type='text/html',
            extension='html', url='https://example.com/document')
        link_template.save()
        wizard = Wizard('office.document.create', config=config)
        wizard.form.template = link_template
        wizard.execute('create_')
        linked, = Attachment.find([
                ('link', '=', 'https://example.com/document'),
                ])
        self.assertEqual(linked.name, 'new-document.html')
        self.assertEqual(linked.type, 'link')

        reader = User(name='Template Reader', login='template-reader')
        reader.save()
        set_user(reader.id, config=config)
        self.assertEqual(
            {template.name for template in Template.find([])},
            {'Letter', 'Minutes', 'Portal'})
        forbidden = Template(
            name='Forbidden', type='text', mime_type='text/markdown',
            extension='md')
        with self.assertRaises(AccessError):
            forbidden.save()
