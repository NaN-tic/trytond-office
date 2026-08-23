import unittest

from proteus import Model
from trytond.pyson import PYSONDecoder
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestConfigurationMenu(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules('office')

        Button = Model.get('ir.model.button')
        Domain = Model.get('ir.action.act_window.domain')
        Menu = Model.get('ir.ui.menu')

        configuration, = Menu.find([
                ('name', '=', 'Configuration'),
                ('parent.name', '=', 'Office'),
                ])

        self.assertEqual(configuration.sequence, 0)
        self.assertEqual(
            [group.name for group in configuration.groups],
            ['Administration'])

        office_configuration, = Menu.find([
                ('name', '=', 'Configuration'),
                ('parent', '=', configuration.id),
                ])
        self.assertEqual(office_configuration.icon, 'tryton-list')

        create, = Menu.find([
                ('name', '=', 'New Document'),
                ('parent.name', '=', 'Office'),
                ])
        self.assertEqual(create.sequence, 5)
        self.assertEqual(create.icon, 'tryton-create')

        attachments, = Menu.find([
                ('name', '=', 'Documents & Attachments'),
                ('parent.name', '=', 'Office'),
                ])
        self.assertEqual(attachments.sequence, 10)

        domains = Domain.find([
                ('act_window.name', '=', 'Documents & Attachments'),
                ], order=[('sequence', 'ASC')])
        self.assertEqual(
            [domain.name for domain in domains],
            ['Documents', 'Attachments', 'All'])
        self.assertEqual(
            [PYSONDecoder().decode(domain.domain) if domain.domain else []
                for domain in domains],
            [[['unlinked', '=', True]],
                [['unlinked', '=', False]], []])

        new_document, = Button.find([
                ('model.name', '=', 'ir.attachment'),
                ('name', '=', 'create_from_template'),
                ])
        self.assertEqual(new_document.string, 'New Document')
