import base64
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from trytond.bus import Bus
from trytond.i18n import gettext
from trytond.ir.avatar import AvatarValidationError, generate
from trytond.model import ChatMixin, ModelSQL, ModelView, fields
from trytond.model.exceptions import AccessError
from trytond.pool import Pool, PoolMeta
from trytond.rpc import RPC
from trytond.transaction import Transaction, check_access


class Chat(ChatMixin, ModelSQL, ModelView):
    "Office Chat"
    __name__ = 'office.chat'

    name = fields.Char("Name")
    users = fields.Many2Many('office.chat-res.user', 'chat', 'user', "Users")
    image = fields.Binary("Image", file_id='image_id')
    image_id = fields.Char("Image ID", readonly=True)
    image_url = fields.Function(fields.Char("Image URL"), 'get_image_url')
    unread_messages = fields.Function(
        fields.Integer("Unread Messages"), 'get_unread_messages')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__rpc__['mark_read'] = RPC(readonly=False, check_access=False)
        cls._buttons['open_chat'] = {'icon': 'tryton-chat'}

    @classmethod
    @ModelView.button
    def open_chat(cls, chats):
        return 'nantic.action.chat'

    @classmethod
    def get_unread_messages(cls, chats, name):
        pool = Pool()
        ChatUser = pool.get('office.chat-res.user')
        Message = pool.get('ir.chat.message')
        counts = dict.fromkeys([c.id for c in chats], 0)
        for participant in ChatUser.search([
                    ('chat', 'in', list(counts)),
                    ('user', '=', Transaction().user),
                    ]):
            counts[participant.chat.id] = Message.search_count([
                    ('channel.resource', '=', str(participant.chat)),
                    ('id', '>', participant.last_read_message or 0),
                    ('user', 'not in', [0, Transaction().user]),
                    ])
        return counts

    @classmethod
    def mark_read(cls, ids, message_id):
        pool = Pool()
        ChatUser = pool.get('office.chat-res.user')
        Message = pool.get('ir.chat.message')
        with check_access():
            cls.read(ids, ['id'])
        for participant in ChatUser.search([
                    ('chat', 'in', ids),
                    ('user', '=', Transaction().user),
                    ]):
            if message_id <= (participant.last_read_message or 0):
                continue
            if Message.search([
                        ('id', '=', message_id),
                        ('channel.resource', '=', str(participant.chat)),
                        ], limit=1):
                ChatUser.write([participant], {
                        'last_read_message': message_id,
                        })

    @staticmethod
    def default_users():
        return [Transaction().user] if Transaction().user else []

    @classmethod
    def preprocess_values(cls, mode, values):
        values = super().preprocess_values(mode, values)
        if values.get('image'):
            try:
                with Image.open(BytesIO(values['image'])) as image:
                    if image.width > 250 or image.height > 250:
                        image.thumbnail((250, 250))
                        output = BytesIO()
                        image.convert('RGBA').save(output, format='PNG')
                        values['image'] = output.getvalue()
            except (UnidentifiedImageError, OSError) as exception:
                raise AvatarValidationError(
                    gettext('ir.msg_avatar_image_error'),
                    str(exception)) from exception
        return values

    @classmethod
    def on_modification(cls, mode, records, field_names=None):
        super().on_modification(mode, records, field_names=field_names)
        if mode in {'create', 'write'}:
            avatars = []
            with Transaction().set_context({'office.chat.image': None}):
                for record in cls.browse([r.id for r in records]):
                    if not record.image:
                        image = generate(100, record.rec_name)
                        if image:
                            record.image = image
                            avatars.append(record)
                cls.save(avatars)

    def get_rec_name(self, name):
        return self.name or ', '.join(sorted(
                (user.rec_name for user in self.users), key=str.casefold))

    @classmethod
    def search_rec_name(cls, name, clause):
        operator = clause[1]
        negative = operator.startswith('not ') or operator == '!='
        if negative:
            operator = '=' if operator == '!=' else operator[4:]
        users = ('users', 'not where' if negative else 'where',
            [('rec_name', operator, *clause[2:])])
        return ['OR',
            [('name', 'not in', [None, '']), ('name', *clause[1:])],
            [('name', 'in', [None, '']), users],
            ]

    def get_image_url(self, name):
        # Return a small image through the authenticated read RPC, without
        # exposing private chat pictures through a public image route.
        with Transaction().set_context({'office.chat.image': None}):
            data = self.__class__(self.id).image
        if data:
            try:
                with Image.open(BytesIO(data)) as image:
                    image.thumbnail((64, 64))
                    output = BytesIO()
                    image.convert('RGBA').save(output, format='PNG')
            except (UnidentifiedImageError, OSError):
                return
            return ('data:image/png;base64,'
                + base64.b64encode(output.getvalue()).decode('ascii'))


class ChatUser(ModelSQL):
    "Office Chat - User"
    __name__ = 'office.chat-res.user'

    chat = fields.Many2One(
        'office.chat', "Chat", required=True, ondelete='CASCADE')
    user = fields.Many2One(
        'res.user', "User", required=True, ondelete='CASCADE')
    last_read_message = fields.Integer("Last Read Message", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('chat')


class Rule(metaclass=PoolMeta):
    __name__ = 'ir.rule'

    @classmethod
    def _get_context(cls, model_name):
        context = super()._get_context(model_name)
        if model_name in {'office.chat', 'ir.chat.channel'}:
            context['user_id'] = Transaction().user
        return context

    @classmethod
    def _get_cache_key(cls, model_names):
        key = super()._get_cache_key(model_names)
        if model_names & {'office.chat', 'ir.chat.channel'}:
            key = (*key, Transaction().user)
        return key


class Channel(metaclass=PoolMeta):
    __name__ = 'ir.chat.channel'

    @classmethod
    def subscribe(cls, resource, username=None):
        if str(resource).startswith('office.chat,') and username is not None:
            cls.check_access(resource)
            if username != Pool().get('res.user')(Transaction().user).login:
                raise AccessError(gettext('office.msg_chat_add_follower'))
        return super().subscribe(resource, username)

    @classmethod
    def subscribe_email(cls, resource, email):
        if str(resource).startswith('office.chat,'):
            cls.check_access(resource)
            raise AccessError(gettext('office.msg_chat_add_follower'))
        return super().subscribe_email(resource, email)

    @classmethod
    def search_followers(cls, resource, text, limit=20):
        if str(resource).startswith('office.chat,'):
            cls.check_access(resource)
            return []
        return super().search_followers(resource, text, limit)

    @classmethod
    def post(cls, resource, content, audience='internal'):
        if str(resource).startswith('office.chat,'):
            audience = 'internal'
        return super().post(resource, content, audience)

    @classmethod
    @check_access
    def check_access(cls, resource):
        super().check_access(resource)
        model, id_ = str(resource).split(',')
        if model == 'office.chat':
            Pool().get(model).read([int(id_)], ['id'])

    @classmethod
    def dispatch_message(cls, message, is_sender):
        resource = message.channel.resource
        if resource.__name__ != 'office.chat':
            return super().dispatch_message(message, is_sender)

        # Bus subscriptions do not check record rules. Sao refreshes via get(),
        # so publish only an invalidation, never the message or its author.
        Bus.publish(f'chat:{resource}', {'type': 'message'})
        if Transaction().context.get('_notify', True):
            users = set(resource.users)
            for follower in message.channel.followers:
                if follower.user in users and not is_sender(follower.user):
                    follower.notify(message)
