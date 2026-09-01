import unittest
from xml.etree import ElementTree

from proteus import Model, launch_action
from trytond.modules.office.attachment import (
    INDEX_TEXT_MAX_LENGTH, split_markdown_paragraphs)
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestAttachmentByCategoryViews(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')

        Action = Model.get('ir.action.act_window', config=config)
        Attachment = Model.get('ir.attachment', config=config)
        Category = Model.get('office.category', config=config)
        Union = Model.get('office.attachment.category', config=config)

        action, = Action.find([
                ('name', '=', 'Documents by Category'),
                ])
        self.assertEqual(action.res_model, 'office.attachment.category')
        self.assertEqual(
            [(view.sequence, view.view.name)
                for view in action.act_window_views],
            [(10, 'attachment_category_tree')])

        with Transaction().start(
                config.database_name, config.user,
                context=config.context):
            ModelData = config.pool.get('ir.model.data')
            CategoryModel = config.pool.get('office.category')
            UnionModel = config.pool.get('office.attachment.category')
            view = UnionModel.fields_view_get(
                view_id=ModelData.get_id(
                    'office', 'view_attachment_category_tree'),
                view_type='tree')
            arch = ElementTree.fromstring(view['arch'])
            fields = arch.findall('./field')
            self.assertEqual(fields[0].get('name'), 'rec_name')
            self.assertEqual(fields[0].get('icon'), 'icon')
            self.assertEqual(fields[1].get('name'), 'record')
            self.assertEqual(fields[1].get('optional'), '0')
            self.assertEqual(arch.get('keyword_open'), '1')

            category_view = CategoryModel.fields_view_get(
                view_id=ModelData.get_id('office', 'view_category_form'),
                view_type='form')
            category_arch = ElementTree.fromstring(category_view['arch'])
            attachments = category_arch.find(
                ".//page[@id='attachments']/field[@name='attachments']")
            self.assertIsNotNone(attachments)

        root = Category(name='Manuals')
        root.save()
        child = Category(name='Accounting', parent=root)
        child.save()
        icon_cases = [
            ('Report.pdf', 'data', 'office-attachment-pdf'),
            ('Letter.docx', 'data', 'office-attachment-document'),
            ('Slides.pptx', 'data', 'office-attachment-presentation'),
            ('Budget.xlsx', 'data', 'office-attachment-spreadsheet'),
            ('Photograph.png', 'data', 'office-attachment-image'),
            ('Notes', 'text', 'office-attachment-text'),
            ('Website', 'link', 'office-attachment-link'),
            ('Archive.bin', 'data', 'office-attachment-file'),
            ('Recording.mp4', 'data', 'office-attachment-video'),
            ]
        with config.set_context(default_unlinked=True):
            for filename, type_, icon in icon_cases:
                icon_attachment = Attachment(name=filename, type=type_)
                if type_ == 'text':
                    icon_attachment.content = 'Text attachment'
                elif type_ == 'link':
                    icon_attachment.link = 'https://example.com'
                icon_attachment.save()
                self.assertEqual(icon_attachment.icon, icon)

        with config.set_context(default_unlinked=True):
            attachment = Attachment(name='Guide.pdf', type='data')
            attachment.categories.append(root)
            attachment.save()
        self.assertEqual(attachment.icon, 'office-attachment-pdf')
        root.reload()
        self.assertEqual(
            [record.id for record in root.attachments], [attachment.id])

        with config.set_context(default_unlinked=True):
            indexed_attachment = Attachment(
                name='Indexed note', type='text',
                content='The quasarneedle is present only in the content')
            indexed_attachment.save()
            named_attachment = Attachment(
                name='quasarneedle.txt', type='text',
                content='Unrelated words')
            named_attachment.save()
        with Transaction().start(
                config.database_name, config.user,
                context=config.context):
            ServerAttachment = config.pool.get('ir.attachment')
            ServerAttachment.indexate([
                    ServerAttachment(indexed_attachment.id),
                    ServerAttachment(named_attachment.id),
                    ])
            Transaction().commit()

        self.assertEqual(
            [record.id for record in Attachment.find([
                        ('content_search', 'ilike', '%quasarneedle%'),
                        ])],
            [indexed_attachment.id])
        self.assertEqual(
            {record.id for record in Attachment.find([
                        ('rec_name', 'ilike', '%quasarneedle%'),
                        ])},
            {indexed_attachment.id, named_attachment.id})
        negative_ids = {
            record.id for record in Attachment.find([
                    ('rec_name', 'not ilike', '%quasarneedle%'),
                    ])}
        self.assertNotIn(indexed_attachment.id, negative_ids)
        self.assertNotIn(named_attachment.id, negative_ids)
        self.assertIn(attachment.id, negative_ids)

        paragraphs = split_markdown_paragraphs(
            'x' * (INDEX_TEXT_MAX_LENGTH * 2 + 17))
        self.assertEqual(len(paragraphs), 3)
        self.assertTrue(all(
                len(paragraph) <= INDEX_TEXT_MAX_LENGTH
                for paragraph in paragraphs))

        roots = launch_action(
            'office.action_attachment_by_category', None, config=config)
        self.assertEqual([record.name for record in roots], ['Manuals'])
        self.assertEqual(roots[0].icon, 'tryton-folder')
        self.assertEqual(
            roots[0].record.__class__.__name__, 'office.category')

        root_union_id = root.id * 2 + 1
        contents = Union.find([
                ('parent', '=', root_union_id),
                ])
        self.assertEqual(
            [record.name for record in contents],
            ['Accounting', 'Guide.pdf'])
        union_attachment, = [
            record for record in contents
            if record.record.__class__.__name__ == 'ir.attachment']
        self.assertEqual(
            union_attachment.icon, 'office-attachment-pdf')

        open_attachment = launch_action(
            'office.wizard_attachment_category_open',
            [union_attachment], config=config)
        self.assertEqual(len(open_attachment.actions), 1)
        self.assertEqual(open_attachment.actions[0][0].id, attachment.id)

        open_category = launch_action(
            'office.wizard_attachment_category_open_from_category',
            [root], config=config)
        self.assertEqual(len(open_category.actions), 1)
        self.assertEqual(
            [record.name for record in open_category.actions[0]],
            ['Accounting', 'Guide.pdf'])
