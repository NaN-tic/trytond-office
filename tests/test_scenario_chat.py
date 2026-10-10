import base64
from io import BytesIO
import unittest
from unittest.mock import patch

from lxml import etree
from PIL import Image
from proteus import Model
from trytond.ir.avatar import generate
from trytond.model.exceptions import AccessError
from trytond.pyson import PYSONDecoder
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules, set_user


class TestChat(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')
        Chat = Model.get('office.chat')
        Channel = Model.get('ir.chat.channel')
        Message = Model.get('ir.chat.message')
        User = Model.get('res.user')
        Menu = Model.get('ir.ui.menu')
        Action = Model.get('ir.action.act_window')
        admin_id = config.user
        alice = User(name='alice', login='office-alice')
        alice.save()
        zoe = User(name='Zoe', login='office-zoe')
        zoe.save()

        menu, = Menu.find([('name', '=', 'Chats')])
        document, = Menu.find([('name', '=', 'New Document')])
        self.assertEqual(menu.parent, document.parent)
        self.assertEqual(menu.sequence, document.sequence - 1)
        self.assertEqual(menu.icon, 'tryton-chat')
        models = dict(Channel._proxy.get_models(config.context))
        self.assertIn('office.chat', models)
        view = Chat._proxy.fields_view_get(None, 'tree', config.context)
        tree = etree.fromstring(view['arch'])
        self.assertEqual(tree.xpath('//field/@name'),
            ['rec_name', 'unread_messages'])
        self.assertEqual(tree.xpath('//prefix/@icon'), ['image_url'])
        self.assertEqual(tree.xpath('//button/@name'), ['open_chat'])
        self.assertEqual(tree.xpath('//button/@string'), ['Open'])
        action, = Action.find([('res_model', '=', 'office.chat')])
        self.assertTrue(PYSONDecoder().decode(
                action.pyson_context)['open_chat_on_activate'])

        set_user(alice, config)
        chat = Chat()
        self.assertEqual([u.id for u in chat.users], [alice.id])
        chat.users.append(User(zoe.id))
        chat.save()
        self.assertEqual(bytes(chat.image), generate(100, 'alice, Zoe'))
        with Image.open(BytesIO(bytes(chat.image))) as avatar:
            self.assertEqual(avatar.size, (100, 100))
        output = BytesIO()
        Image.new('RGB', (1000, 750), 'blue').save(output, format='PNG')
        chat.image = output.getvalue()
        chat.save()
        chat_id = chat.id
        resource = f'office.chat,{chat_id}'
        self.assertEqual(Chat._proxy.open_chat([chat_id], config.context),
            'nantic.action.chat')
        self.assertEqual(chat.unread_messages, 0)
        self.assertEqual(chat.rec_name, 'alice, Zoe')
        self.assertTrue(chat.image_id)
        with Image.open(BytesIO(bytes(chat.image))) as avatar:
            self.assertEqual(avatar.size, (250, 188))
        with Image.open(BytesIO(base64.b64decode(
                        chat.image_url.split(',', 1)[1]))) as thumbnail:
            self.assertEqual(thumbnail.size, (64, 48))
        output = BytesIO()
        Image.new('RGBA', (400, 800), 'blue').save(output, format='PNG')
        chat.image = output.getvalue()
        chat.save()
        with Image.open(BytesIO(bytes(chat.image))) as avatar:
            self.assertEqual(avatar.size, (125, 250))
        output = BytesIO()
        Image.new('RGB', (128, 96), 'blue').save(output, format='PNG')
        chat.image = output.getvalue()
        chat.save()
        self.assertEqual(bytes(chat.image), output.getvalue())
        chat.image = None
        chat.save()
        self.assertEqual(bytes(chat.image), generate(100, 'alice, Zoe'))
        self.assertTrue(chat.image_url)
        self.assertEqual(Chat.find([('rec_name', 'ilike', '%Zoe%')]), [chat])
        self.assertEqual(Chat.find([('rec_name', 'not ilike', '%Zoe%')]), [])
        chat.name = 'Planning'
        chat.save()
        self.assertEqual(chat.rec_name, 'Planning')
        self.assertEqual(Chat.find([('rec_name', 'ilike', '%Zoe%')]), [])
        self.assertEqual(Chat.find([('rec_name', 'ilike', '%Planning%')]), [chat])
        # Existing avatars remain unchanged; clearing one regenerates it
        # using the current chat name.
        self.assertEqual(bytes(chat.image), generate(100, 'alice, Zoe'))
        chat.image = None
        chat.save()
        self.assertEqual(bytes(chat.image), generate(100, 'Planning'))

        Channel._proxy.subscribe(resource, None, config.context)
        with self.assertRaises(AccessError):
            Channel._proxy.subscribe(resource, zoe.login, config.context)
        with self.assertRaises(AccessError):
            Channel._proxy.subscribe_email(
                resource, 'outside@example.com', config.context)
        self.assertEqual(Channel._proxy.search_followers(
                resource, 'Zoe', 20, config.context), [])
        with patch('trytond.modules.office.chat.Bus.publish') as publish:
            Channel._proxy.post(resource, 'Private message', 'public',
                config.context)
        self.assertIn(
            ((f'chat:{resource}', {'type': 'message'}), {}),
            [(call.args, call.kwargs) for call in publish.call_args_list])
        messages = Channel._proxy.get(resource, None, None, config.context)
        self.assertEqual(messages[-1]['content'], 'Private message')
        self.assertEqual(messages[-1]['audience'], 'internal')
        message_id = messages[-1]['id']
        self.assertEqual(Chat(chat_id).unread_messages, 0)

        set_user(zoe, config)
        self.assertEqual([c.id for c in Chat.find([])], [chat_id])
        self.assertEqual(Chat(chat_id).unread_messages, 1)
        self.assertEqual(Channel._proxy.get(
                resource, None, None, config.context)[-1]['content'],
            'Private message')
        # Fetching history alone does not acknowledge messages.
        self.assertEqual(Chat(chat_id).unread_messages, 1)
        Chat._proxy.mark_read([chat_id], message_id, config.context)
        self.assertEqual(Chat(chat_id).unread_messages, 0)
        Chat._proxy.mark_read([chat_id], message_id - 1, config.context)
        self.assertEqual(Chat(chat_id).unread_messages, 0)
        Channel._proxy.subscribe(resource, None, config.context)
        Channel._proxy.post(resource, 'Reply', 'public', config.context)

        set_user(alice, config)
        self.assertEqual(Chat(chat_id).unread_messages, 1)
        set_user(zoe, config)
        self.assertEqual(Chat(chat_id).unread_messages, 0)

        # Users with identical groups must not share a cached access domain.
        set_user(admin_id, config)
        self.assertEqual(Chat.find([]), [])
        self.assertEqual(Channel.find([('resource', '=', resource)]), [])
        self.assertEqual(Message.find([('id', '=', message_id)]), [])
        with self.assertRaises(AccessError):
            Chat._proxy.read([chat_id], ['name', 'image_url'], config.context)
        with self.assertRaises(AccessError):
            Channel._proxy.get(resource, None, None, config.context)
        with self.assertRaises(AccessError):
            Channel._proxy.post(resource, 'Intrusion', 'internal',
                config.context)
        with self.assertRaises(AccessError):
            Channel._proxy.subscribe(resource, None, config.context)
        with self.assertRaises(AccessError):
            Chat._proxy.mark_read([chat_id], message_id, config.context)
        with self.assertRaises(AccessError):
            Chat._proxy.open_chat([chat_id], config.context)
        with self.assertRaises(AccessError):
            Message._proxy.read([message_id], ['content'], config.context)
        with self.assertRaises(AccessError):
            Chat._proxy.write([chat_id],
                {'users': [('add', [admin_id])]}, config.context)

        set_user(alice, config)
        chat = Chat(chat_id)
        chat.users.pop(chat.users.index(User(zoe.id)))
        chat.name = None
        chat.save()
        self.assertEqual(chat.rec_name, 'alice')
        Channel._proxy.post(resource, 'After removal', 'internal',
            config.context)
        set_user(zoe, config)
        self.assertEqual(Chat.find([]), [])
        with self.assertRaises(AccessError):
            Channel._proxy.get(resource, None, None, config.context)
        Notification = Model.get('res.notification')
        self.assertFalse(Notification.find([
                    ('description', '=', 'After removal'),
                    ]))
