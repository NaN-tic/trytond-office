import unittest

from proteus import Model
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestDocumentMigration(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')
        Group = Model.get('res.group', config=config)
        Lang = Model.get('ir.lang', config=config)
        Category = Model.get('office.category', config=config)
        AttachmentModel = Model.get('ir.attachment', config=config)

        group = Group(name='Legacy Readers')
        group.save()
        language, = Lang.find([('code', '=', 'en')])
        category = Category(name='Legacy')
        category.save()
        file_sync_attachment = AttachmentModel(
            name='Legacy unlinked attachment', type='text',
            content='Existing attachment', resource=category)
        file_sync_attachment.save()

        with Transaction().start(
                config.database_name, config.user,
                context=config.context) as transaction:
            cursor = transaction.connection.cursor()
            cursor.execute(
                'CREATE TABLE brainbow_document ('
                'id INTEGER PRIMARY KEY, name VARCHAR, text TEXT, '
                'language INTEGER, resource VARCHAR, active BOOLEAN, '
                'replaced_by INTEGER)')
            cursor.execute(
                'CREATE TABLE brainbow_document_reader_group ('
                'id INTEGER PRIMARY KEY, document INTEGER, '
                'reader_group INTEGER)')
            cursor.execute(
                'CREATE TABLE brainbow_document_tag ('
                'id INTEGER PRIMARY KEY, document INTEGER, tag INTEGER)')
            cursor.execute(
                'INSERT INTO brainbow_document '
                '(id, name, text, language, resource, active, replaced_by) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (1, 'Legacy Guide', 'Migrated text', language.id,
                    None, True, 2))
            cursor.execute(
                'INSERT INTO brainbow_document '
                '(id, name, text, language, resource, active, replaced_by) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (2, 'Current Guide', 'Current text', language.id,
                    None, True, None))
            cursor.execute(
                'INSERT INTO brainbow_document_reader_group '
                '(id, document, reader_group) VALUES (?, ?, ?)',
                (1, 1, group.id))
            cursor.execute(
                'INSERT INTO brainbow_document_tag '
                '(id, document, tag) VALUES (?, ?, ?)',
                (1, 1, category.id))

            pool = Pool(config.database_name)
            Attachment = pool.get('ir.attachment')
            Unlinked = pool.get('office.unlinked')
            ReaderGroup = pool.get('office.attachment-reader-group')
            AttachmentCategory = pool.get('office.attachment-category')
            unlinked = Unlinked.get_singleton()
            self.assertIsNotNone(unlinked)
            cursor.execute(
                'DELETE FROM office_unlinked WHERE id = ?',
                (unlinked.id,))
            cursor.execute('DROP TABLE "office_attachment-category"')
            self.assertIsNone(Unlinked.get_singleton())
            transaction._locked_tables.add(Unlinked._table)
            Attachment.__register__('office')
            ReaderGroup.__register__('office')
            AttachmentCategory.__register__('office')

            attachment, = Attachment.search([
                    ('name', '=', 'Legacy Guide'),
                    ])
            self.assertEqual(attachment.type, 'text')
            self.assertEqual(attachment.content, 'Migrated text')
            self.assertEqual(attachment.language.id, language.id)
            self.assertTrue(attachment.unlinked)
            self.assertEqual(attachment.replaced_by.name, 'Current Guide')
            self.assertEqual(
                attachment.resource.__name__, 'office.unlinked')
            self.assertIsNotNone(Unlinked.get_singleton())
            self.assertEqual(
                [item.id for item in attachment.reader_groups], [group.id])
            self.assertEqual(
                [item.id for item in attachment.categories], [category.id])
            migrated_file_sync_attachment = Attachment(
                file_sync_attachment.id)
            self.assertTrue(migrated_file_sync_attachment.unlinked)
            self.assertEqual(
                migrated_file_sync_attachment.resource.__name__,
                'office.unlinked')
            transaction.commit()
