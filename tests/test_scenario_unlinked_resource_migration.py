import unittest

from proteus import Model
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestUnlinkedResourceMigration(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')
        Attachment = Model.get('ir.attachment', config=config)
        User = Model.get('res.user', config=config)
        document = Attachment(
            name='Unlinked document', type='text', content='Document',
            unlinked=True)
        document.save()
        archived = Attachment(
            name='Archived document', type='text', content='Archive',
            unlinked=True, active=False)
        archived.save()
        linked = Attachment(
            name='Linked document', type='text', content='Linked',
            resource=User(config.user))
        linked.save()
        old_resource = str(document.resource)
        linked_resource = str(linked.resource)

        with Transaction().start(
                config.database_name, config.user,
                context=config.context) as transaction:
            AttachmentModel = config.pool.get('ir.attachment')
            Unlinked = config.pool.get('office.unlinked')
            unlinked = Unlinked.__table__()
            singleton = Unlinked.get_singleton()
            new_id = singleton.id + 7
            cursor = transaction.connection.cursor()
            cursor.execute(*unlinked.update(
                    [unlinked.id], [new_id],
                    where=unlinked.id == singleton.id))
            transaction.commit()

        # A stored reference to the old singleton is returned as None.
        values, = Attachment._proxy.read(
            [document.id], ['resource'], config.context)
        self.assertIsNone(values['resource'])

        with Transaction().start(
                config.database_name, config.user,
                context=config.context) as transaction:
            table = AttachmentModel.__table__()
            cursor = transaction.connection.cursor()
            cursor.execute(*table.select(
                    table.resource, where=table.id == document.id))
            self.assertEqual(cursor.fetchone()[0], old_resource)
            AttachmentModel.__register__('office')
            transaction.commit()

        new_resource = 'office.unlinked,%s' % new_id
        for record in [document, archived]:
            record.reload()
            self.assertEqual(str(record.resource), new_resource)
            self.assertTrue(record.unlinked)
        self.assertFalse(archived.active)
        linked.reload()
        self.assertEqual(str(linked.resource), linked_resource)
        self.assertFalse(linked.unlinked)

        # Updating the module again must preserve the repaired references.
        with Transaction().start(
                config.database_name, config.user,
                context=config.context) as transaction:
            AttachmentModel.__register__('office')
            transaction.commit()
        document.reload()
        self.assertEqual(str(document.resource), new_resource)
