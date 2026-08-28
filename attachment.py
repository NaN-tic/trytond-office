import base64
import json
import logging
import mimetypes
import tempfile

from magic import Magic
from markitdown import (
    FileConversionException, MarkItDown, UnsupportedFormatException)
from sql import Literal, Null, Table
from sql.conditionals import Coalesce
from sql.functions import CurrentTimestamp
from sql.operators import Equal

from trytond import backend
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model import (
    DeactivableMixin, Exclude, fields, ModelSingleton, ModelSQL, ModelView,
    Unique, tree)
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval
from trytond.transaction import Transaction, without_check_access

logger = logging.getLogger(__name__)


def migrate_category_relation(model, module_name, old_tables, old_constraint):
    for old_table in old_tables:
        if (backend.TableHandler.table_exist(old_table)
                and not backend.TableHandler.table_exist(model._table)):
            backend.TableHandler.table_rename(old_table, model._table)
    handler = model.__table_handler__(module_name)
    if handler.column_exist('tag') and not handler.column_exist('category'):
        handler.column_rename('tag', 'category')
    handler.drop_constraint(old_constraint)


def split_markdown_paragraphs(text):
    paragraphs = []
    current_paragraph = ''
    for line in (text or '').split('\n'):
        line = line.strip()
        if not line and current_paragraph:
            paragraphs.append(current_paragraph.strip())
            current_paragraph = ''
        elif line.startswith(('- ', '* ', '+ ')) or (
                len(line.split('.')) >= 2
                and line.split('.')[0].isdigit()
                and line.split('.')[1].startswith(' ')):
            if current_paragraph:
                paragraphs.append(current_paragraph.strip())
            item = line.lstrip('-*+0123456789. ').strip()
            if item:
                paragraphs.append(item)
            current_paragraph = ''
        elif line:
            current_paragraph += line + ' '
    if current_paragraph:
        paragraphs.append(current_paragraph.strip())
    return paragraphs


class Index(metaclass=PoolMeta):
    __name__ = 'kb.index'

    @classmethod
    def _get_resources(cls):
        return super()._get_resources() + ['ir.attachment']


class Category(DeactivableMixin, tree(separator=' / '), ModelSQL, ModelView):
    'Office Category'
    __name__ = 'office.category'

    name = fields.Char('Name', required=True, translate=True)
    view = fields.Boolean('View')
    unique = fields.Boolean('Unique', states={
            'invisible': ~Bool(Eval('view')),
            })
    required = fields.Boolean('Required', states={
            'invisible': ~Bool(Eval('view')),
            })
    parent = fields.Many2One('office.category', 'Parent')
    children = fields.One2Many('office.category', 'parent', 'Children')
    description = fields.Text('Description')
    attachments = fields.Many2Many(
        'office.attachment-category', 'category', 'attachment', 'Attachments')
    read_only_groups = fields.Many2Many(
        'office.category-read-only-group', 'category', 'group',
        'Read-only Groups')
    read_write_groups = fields.Many2Many(
        'office.category-read-write-group', 'category', 'group',
        'Read-write Groups')
    read_only_users = fields.Many2Many(
        'office.category-read-only-user', 'category', 'user',
        'Read-only Users')
    read_write_users = fields.Many2Many(
        'office.category-read-write-user', 'category', 'user',
        'Read-write Users')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints = [
            ('name_parent_exclude',
                Exclude(table,
                    (table.name, Equal),
                    (Coalesce(table.parent, -1), Equal)),
                'office.msg_category_name_unique'),
            ]
        cls._order.insert(0, ('name', 'ASC'))

    @classmethod
    def __register__(cls, module_name):
        for old_table in ['brainbow_category', 'brainbow_tag', 'office_tag']:
            if (backend.TableHandler.table_exist(old_table)
                    and not backend.TableHandler.table_exist(cls._table)):
                backend.TableHandler.table_rename(old_table, cls._table)
        super().__register__(module_name)

    def access_users(self):
        "Return the inherited read-write and read-only user sets."
        read_write = set()
        read_only = set()
        category = self
        while category:
            read_write.update(category.read_write_users)
            read_only.update(category.read_only_users)
            for group in category.read_write_groups:
                read_write.update(group.users)
            for group in category.read_only_groups:
                read_only.update(group.users)
            category = category.parent
        read_only.difference_update(read_write)
        return read_write, read_only


class Unlinked(ModelSingleton, ModelSQL, ModelView):
    'Unlinked Attachments'
    __name__ = 'office.unlinked'

    name = fields.Char('Name', required=True)

    @staticmethod
    def default_name():
        return 'Unlinked Attachments'

    @classmethod
    def __register__(cls, module_name):
        old_table = 'brainbow_unlinked'
        if (backend.TableHandler.table_exist(old_table)
                and not backend.TableHandler.table_exist(cls._table)):
            backend.TableHandler.table_rename(old_table, cls._table)
        super().__register__(module_name)


class Attachment(DeactivableMixin, ModelView, metaclass=PoolMeta):
    'Attachment'
    __name__ = 'ir.attachment'

    mimetype = fields.Char('Mimetype', readonly=True)
    content = fields.Text('Content', states={
            'readonly': Eval('type') != 'text',
            }, depends=['type'])
    data_updated = fields.Boolean('Data Updated', readonly=True)
    language = fields.Many2One('ir.lang', 'Language')
    unlinked = fields.Boolean('Unlinked')
    reader_groups = fields.Many2Many(
        'office.attachment-reader-group', 'attachment', 'reader_group',
        'Reader Groups')
    writer_groups = fields.Many2Many(
        'office.attachment-writer-group', 'attachment', 'writer_group',
        'Writer Groups')
    categories_char = fields.Function(
        fields.Char('Categories'), 'get_categories_char',
        searcher='search_categories_char')
    categories = fields.Many2Many(
        'office.attachment-category', 'attachment', 'category', 'Categories',
        domain=[('view', '=', False)])
    replaced_by = fields.Many2One(
        'ir.attachment', 'Replaced By', readonly=True,
        ondelete='SET NULL', domain=[('id', '!=', Eval('id', -1))],
        states={'invisible': ~Bool(Eval('replaced_by'))})

    @classmethod
    def __setup__(cls):
        super().__setup__()
        if ('text', 'Text') not in cls.type.selection:
            cls.type.selection.append(('text', 'Text'))
        cls.resource.states['invisible'] = Bool(Eval('unlinked'))
        cls.resource.depends.add('unlinked')
        cls.description.states['invisible'] = Eval('type') == 'text'
        cls.description.depends.add('type')
        cls.language.states['invisible'] = ~Eval('type').in_(['text', 'data'])
        cls.language.depends.add('type')
        cls._buttons.update({
                'create_from_template': {
                    'invisible': (
                        ((Eval('type') != 'data') | Bool(Eval('data')))
                        & ((Eval('type') != 'text')
                            | Bool(Eval('content')))
                        & ((Eval('type') != 'link') | Bool(Eval('link')))),
                    'depends': ['type', 'data', 'content', 'link'],
                    },
                })

    @staticmethod
    def default_name():
        Configuration = Pool().get('office.configuration')
        default_filename = Configuration(1).default_filename
        if not default_filename or default_filename == 'unnamed document':
            return gettext('office.msg_unnamed_document')
        return default_filename

    @fields.depends('data', 'name')
    def on_change_data(self):
        if self.data is None and not self.name:
            self.name = self.default_name()

    @classmethod
    @ModelView.button_action('office.wizard_document_create')
    def create_from_template(cls, attachments):
        pass

    @classmethod
    def _get_unlinked_resource(cls):
        Unlinked = Pool().get('office.unlinked')
        unlinked = Unlinked.get_singleton()
        if not unlinked:
            with without_check_access():
                unlinked, = Unlinked.create([{}])
        return unlinked

    @classmethod
    def __register__(cls, module_name):
        super().__register__(module_name)
        if not backend.TableHandler.table_exist('brainbow_document'):
            return

        class LegacyDocument:
            _table = 'brainbow_document'

        LegacyDocument.__name__ = 'brainbow.document.legacy'
        handler = backend.TableHandler(LegacyDocument)
        if not handler.column_exist('attachment'):
            handler.add_column('attachment', 'INTEGER')

        cursor = Transaction().connection.cursor()
        document = Table('brainbow_document')
        replaced_by = (document.replaced_by
            if handler.column_exist('replaced_by') else Literal(None))
        cursor.execute(*document.select(
                document.id, document.name, document.text,
                document.language, document.resource, document.active,
                replaced_by,
                where=document.attachment == Null))
        rows = cursor.fetchall()
        if rows:
            dummy = str(cls._get_unlinked_resource())
            transaction = Transaction()
            attachment_table = cls.__table__()
            mapping = {}
            with Transaction().set_context(
                    office_migration=True, office_skip_index=True,
                    file_sync_skip=True, _check_access=False):
                for (document_id, name, content, language, resource, active,
                        replaced_by) in rows:
                    columns = [
                        attachment_table.create_uid,
                        attachment_table.create_date,
                        attachment_table.name,
                        attachment_table.type,
                        attachment_table.content,
                        attachment_table.language,
                        attachment_table.resource,
                        attachment_table.unlinked,
                        attachment_table.active,
                        ]
                    values = [
                        transaction.user, CurrentTimestamp(), name, 'text',
                        content, language, resource or dummy,
                        not bool(resource), active,
                        ]
                    attachment_id = transaction.database.nextid(
                        transaction.connection, cls._table)
                    if attachment_id:
                        columns.append(attachment_table.id)
                        values.append(attachment_id)
                    cursor.execute(*attachment_table.insert(
                            columns, [values],
                            returning=([attachment_table.id]
                                if (not attachment_id
                                    and transaction.database.has_returning())
                                else None)))
                    if not attachment_id:
                        if transaction.database.has_returning():
                            attachment_id, = cursor.fetchone()
                        else:
                            attachment_id = transaction.database.lastid(cursor)
                    attachment = cls(attachment_id)
                    mapping[document_id] = (attachment, replaced_by)
                    cursor.execute(*document.update(
                            [document.attachment], [attachment.id],
                            where=document.id == document_id))
                if handler.column_exist('replaced_by'):
                    replacement = Table('brainbow_document')
                    cursor.execute(*document.join(replacement,
                            condition=(document.replaced_by
                                == replacement.id)).select(
                                    document.attachment,
                                    replacement.attachment,
                                    where=((document.attachment != Null)
                                        & (replacement.attachment != Null))))
                    for attachment_id, replacement_id in cursor.fetchall():
                        cursor.execute(*attachment_table.update(
                                [attachment_table.replaced_by],
                                [replacement_id],
                                where=attachment_table.id == attachment_id))
            cls._migrate_document_references(mapping)
        cls._migrate_file_sync_unlinked()

    @classmethod
    def _migrate_document_references(cls, mapping):
        cursor = Transaction().connection.cursor()
        if backend.TableHandler.table_exist('kb_index'):
            index = Table('kb_index')
            for document_id, (attachment, _) in mapping.items():
                cursor.execute(*index.update(
                        [index.resource], [str(attachment)],
                        where=(index.resource
                            == f'brainbow.document,{document_id}')))
        if backend.TableHandler.table_exist('file_sync_entry'):
            entry = Table('file_sync_entry')

            class LegacyEntry:
                _table = 'file_sync_entry'

            LegacyEntry.__name__ = 'file.sync.entry.legacy'
            handler = backend.TableHandler(LegacyEntry)
            if handler.column_exist('document'):
                for document_id, (attachment, _) in mapping.items():
                    cursor.execute(*entry.update(
                            [entry.attachment], [attachment.id],
                            where=((entry.document == document_id)
                                & (entry.attachment == Null))))

    @classmethod
    def _migrate_file_sync_unlinked(cls):
        cursor = Transaction().connection.cursor()
        attachment = cls.__table__()
        dummy = str(cls._get_unlinked_resource())
        cursor.execute(*attachment.update(
                [attachment.unlinked, attachment.resource],
                [True, dummy],
                where=attachment.resource.like('office.category,%')))

    @staticmethod
    def default_unlinked():
        return Transaction().context.get('default_unlinked', False)

    @classmethod
    def default_resource(cls):
        if Transaction().context.get('default_unlinked'):
            return str(cls._get_unlinked_resource())
        return super().default_resource()

    @fields.depends('unlinked', 'resource')
    def on_change_unlinked(self):
        if self.unlinked:
            self.resource = self.__class__._get_unlinked_resource()
        elif self.resource and self.resource.__name__ == 'office.unlinked':
            self.resource = None

    def get_categories_char(self, name):
        return ', '.join(category.rec_name for category in self.categories)

    @classmethod
    def search_categories_char(cls, name, clause):
        return [('categories.name',) + tuple(clause[1:])]

    @classmethod
    def search_rec_name(cls, name, clause):
        return ['OR',
            ('name',) + tuple(clause[1:]),
            ('content',) + tuple(clause[1:]),
            ]

    @classmethod
    def create(cls, vlist):
        vlist = [values.copy() for values in vlist]
        dummy = None
        for values in vlist:
            if values.get(
                    'unlinked', Transaction().context.get(
                        'default_unlinked', False)):
                if dummy is None:
                    dummy = str(cls._get_unlinked_resource())
                values['unlinked'] = True
                values['resource'] = dummy
            cls.calculate_fields(values)
        attachments = super().create(vlist)
        if not Transaction().context.get('office_migration'):
            cls.__queue__.extract_content(attachments)
        return attachments

    @classmethod
    def write(cls, *args):
        dummy = None
        actions = iter(args)
        new_args = []
        to_extract = []
        for records, values in zip(actions, actions):
            values = values.copy()
            if values.get('unlinked'):
                if dummy is None:
                    dummy = str(cls._get_unlinked_resource())
                values['resource'] = dummy
            cls.calculate_fields(values)
            new_args.extend([records, values])
            if values.get('data_updated'):
                to_extract.extend(records)
        super().write(*new_args)
        if to_extract and not Transaction().context.get('office_migration'):
            cls.__queue__.extract_content(to_extract)

    @staticmethod
    def calculate_fields(values):
        if 'data' not in values:
            return
        values.setdefault('data_updated', True)
        data = values['data']
        if not data:
            values.setdefault('content', None)
            values.setdefault('mimetype', None)
        else:
            try:
                mimetype = Magic(mime=True).from_buffer(data)
            except TypeError:
                mimetype = None
            values.setdefault('mimetype', mimetype)

    @classmethod
    def extract_content(cls, attachments):
        converter = MarkItDown()
        for attachment in attachments:
            if attachment.type == 'text':
                attachment.data_updated = False
                attachment.set_language()
                continue
            if not attachment.data_updated:
                if attachment.content and not attachment.language:
                    attachment.set_language()
                continue
            attachment.data_updated = False
            if not attachment.data:
                attachment.content = None
                continue
            if not attachment.mimetype:
                if '.' not in attachment.name:
                    continue
                extension = attachment.name.rsplit('.', 1)[-1]
            else:
                extension = mimetypes.guess_extension(attachment.mimetype)
            if not extension:
                continue
            extracted_content = None
            try:
                with tempfile.NamedTemporaryFile(
                        mode='wb', suffix=extension.lower()) as temp_file:
                    temp_file.write(attachment.data)
                    temp_file.flush()
                    result = converter.convert(temp_file.name)
                    extracted_content = result.text_content.replace(
                        '\x00', '')
            except (FileConversionException,
                    UnsupportedFormatException) as exception:
                logger.warning(
                    'Could not extract content using MarkItDown: %s',
                    exception)
            attachment.content = extracted_content
            if not (attachment.content or '').strip():
                image_data = attachment._image_ocr()
                if image_data is not None:
                    attachment.content = image_data['literal_text']
                    attachment.description = image_data['description']
            attachment.set_language()
        cls.save(attachments)

    def _image_ocr(self):
        if not (self.mimetype or '').startswith('image/'):
            return
        Configuration = Pool().get('office.configuration')
        model = Configuration(1).image_ocr_model
        if not model:
            return
        language = Pool().get('ir.configuration').get_language()
        encoded = base64.b64encode(self.data).decode('ascii')
        response, error = model.get_completion([{
                    'role': 'developer',
                    'content': (
                        'Analyze this image and return only valid JSON, without '
                        'wrapping it in Markdown or a code fence, using exactly '
                        'this structure: '
                        '{"literal_text": "", "description": ""}. '
                        'In literal_text, transcribe all visible text exactly '
                        'as written and preserve its reading order. You may use '
                        'Markdown syntax inside literal_text to reproduce the '
                        'document structure, including headings, lists, tables '
                        'and emphasis. In '
                        'description, describe the visual content and context '
                        'of the image using the database default language '
                        f'({language}). Use an empty string when a value is '
                        'not available and do not invent content.'),
                    }, {
                    'role': 'user',
                    'content': [{
                            'type': 'image_url',
                            'image_url': {
                                'url': (
                                    f'data:{self.mimetype};base64,{encoded}'),
                                },
                            }],
                }], self)
        if error:
            logger.error('Could not extract image text using AI: %s', response)
            return
        content = response.choices[0].message.content
        try:
            image_data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.error('Image AI returned invalid JSON: %s', content)
            return
        if (not isinstance(image_data, dict)
                or not all(isinstance(image_data.get(key), str)
                    for key in ['literal_text', 'description'])):
            logger.error('Image AI returned an invalid structure: %s', content)
            return
        return image_data

    def _completion(self, instruction, model_field):
        if not self.content or not self.content.strip():
            return
        Configuration = Pool().get('ai.configuration')
        model = getattr(Configuration(1), model_field)
        if not model:
            logger.error('Office AI model "%s" is not configured.',
                model_field)
            return
        if model.provider != 'openrouter':
            logger.error('Office AI models must use OpenRouter.')
            return
        response, error = model.get_completion([{
                    'role': 'developer',
                    'content': instruction,
                    }, {
                    'role': 'user',
                    'content': self.content,
                    }], self)
        if error:
            logger.error('Could not analyze attachment: %s', response)
            return
        return response.choices[0].message.content.strip()

    def set_name(self):
        if self.name:
            return
        self.name = self._completion(
            'Create a short, unique and relevant title for this text.',
            'office_title_model')

    def set_language(self):
        if self.language:
            return
        code = self._completion(
            'Detect the language and output only its ISO 639 language code.',
            'office_language_model')
        if not code:
            return
        languages = Pool().get('ir.lang').search([
                ('code', '=', code.lower()),
                ], limit=1)
        if languages:
            self.language = languages[0]

    @fields.depends('name', 'language', 'content', 'type')
    def on_change_content(self):
        if self.type == 'text':
            self.set_name()
            self.set_language()

    @classmethod
    def validate_fields(cls, attachments, field_names):
        super().validate_fields(attachments, field_names)
        cls._check_categories(attachments, field_names)
        cls.indexate(attachments, field_names)

    @classmethod
    def indexate(cls, attachments, field_names=None):
        if Transaction().context.get('office_skip_index'):
            return
        if field_names and not field_names & {
                'active', 'content', 'language'}:
            return
        pool = Pool()
        Index = pool.get('kb.index')
        default_language = pool.get('ir.configuration').get_language()
        all_indexes = {}
        for attachment in attachments:
            indexes = []
            if attachment.active:
                language = (attachment.language.code
                    if attachment.language else default_language)
                indexes = [Index(
                        text=paragraph,
                        language_code=language,
                        resource=attachment,
                        weight='B')
                    for paragraph in split_markdown_paragraphs(
                        attachment.content)]
                indexes.append(Index(
                        text=attachment.name,
                        language_code=language,
                        resource=attachment,
                        weight='A'))
                if attachment.description:
                    indexes.append(Index(
                            text=attachment.description,
                            language_code=language,
                            resource=attachment,
                            weight='C'))
            all_indexes[attachment] = indexes
        Index.compute_indexes(all_indexes)

    @classmethod
    def delete(cls, attachments):
        attachments = list(attachments)
        active = [attachment for attachment in attachments
            if attachment.active]
        inactive = [attachment for attachment in attachments
            if not attachment.active]
        if active:
            cls.write(active, {'active': False})
        if inactive:
            Index = Pool().get('kb.index')
            Index.delete(Index.search([('resource', 'in', inactive)]))
            super().delete(inactive)

    @classmethod
    def _check_categories(cls, attachments, field_names):
        if field_names and not field_names & {'categories'}:
            return
        Category = Pool().get('office.category')
        required_categories = Category.search([
                ('required', '=', True),
                ('view', '=', True),
                ])
        unique_categories = Category.search([
                ('unique', '=', True),
                ('view', '=', True),
                ])
        required_children = [Category.search([
                    ('parent', 'child_of', [required]),
                    ('id', '!=', required),
                    ]) for required in required_categories]
        for attachment in attachments:
            missing = list(required_children)
            for category in attachment.categories:
                missing = [children for children in missing
                    if category not in children]
            if missing:
                raise UserError(gettext(
                    'office.msg_missing_categories',
                    document=attachment.rec_name,
                    categories=', '.join(
                        category.name
                        for category in required_categories[:3])))
            for unique_category in unique_categories:
                children = Category.search([
                        ('parent', 'child_of', unique_category),
                        ])
                if len(set(children) & set(attachment.categories)) > 1:
                    raise UserError(gettext(
                        'office.msg_repeated_unique',
                        document=attachment.rec_name,
                        category=unique_category.rec_name))


class AttachmentReaderGroup(ModelSQL):
    'Attachment - Reader Group'
    __name__ = 'office.attachment-reader-group'

    attachment = fields.Many2One(
        'ir.attachment', 'Attachment', required=True, ondelete='CASCADE')
    reader_group = fields.Many2One(
        'res.group', 'Reader Group', required=True, ondelete='CASCADE')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('attachment')
        table = cls.__table__()
        cls._sql_constraints += [(
                'attachment_reader_group_uniq',
                Unique(table, table.attachment, table.reader_group),
                'office.msg_attachment_reader_group_uniq')]

    @classmethod
    def __register__(cls, module_name):
        old_table = 'brainbow_attachment-reader-group'
        if (backend.TableHandler.table_exist(old_table)
                and not backend.TableHandler.table_exist(cls._table)):
            backend.TableHandler.table_rename(old_table, cls._table)
        super().__register__(module_name)
        cls._migrate_documents()

    @classmethod
    def _migrate_documents(cls):
        table_name = 'brainbow_document-reader-group'
        if not backend.TableHandler.table_exist(table_name):
            return
        cursor = Transaction().connection.cursor()
        document = Table('brainbow_document')
        relation = Table(table_name)
        cursor.execute(*relation.join(document,
                condition=document.id == relation.document).select(
                    document.attachment, relation.reader_group,
                    where=document.attachment != Null))
        for attachment, group in cursor.fetchall():
            if not cls.search([
                        ('attachment', '=', attachment),
                        ('reader_group', '=', group),
                        ], limit=1):
                cls.create([{
                            'attachment': attachment,
                            'reader_group': group,
                            }])


class AttachmentWriterGroup(ModelSQL):
    'Attachment - Writer Group'
    __name__ = 'office.attachment-writer-group'

    attachment = fields.Many2One(
        'ir.attachment', 'Attachment', required=True, ondelete='CASCADE')
    writer_group = fields.Many2One(
        'res.group', 'Writer Group', required=True, ondelete='CASCADE')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('attachment')
        table = cls.__table__()
        cls._sql_constraints += [(
                'attachment_writer_group_uniq',
                Unique(table, table.attachment, table.writer_group),
                'office.msg_attachment_writer_group_uniq')]

    @classmethod
    def __register__(cls, module_name):
        old_table = 'brainbow_attachment-writer-group'
        if (backend.TableHandler.table_exist(old_table)
                and not backend.TableHandler.table_exist(cls._table)):
            backend.TableHandler.table_rename(old_table, cls._table)
        super().__register__(module_name)
        table_name = 'brainbow_document-writer-group'
        if not backend.TableHandler.table_exist(table_name):
            return
        cursor = Transaction().connection.cursor()
        document = Table('brainbow_document')
        relation = Table(table_name)
        cursor.execute(*relation.join(document,
                condition=document.id == relation.document).select(
                    document.attachment, relation.writer_group,
                    where=document.attachment != Null))
        for attachment, group in cursor.fetchall():
            if not cls.search([
                        ('attachment', '=', attachment),
                        ('writer_group', '=', group),
                        ], limit=1):
                cls.create([{
                            'attachment': attachment,
                            'writer_group': group,
                            }])


class AttachmentCategory(ModelSQL):
    'Attachment - Category'
    __name__ = 'office.attachment-category'

    attachment = fields.Many2One(
        'ir.attachment', 'Attachment', required=True, ondelete='CASCADE')
    category = fields.Many2One(
        'office.category', 'Category', required=True, ondelete='CASCADE')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.update({'attachment', 'category'})
        table = cls.__table__()
        cls._sql_constraints += [(
                'attachment_category_uniq',
                Unique(table, table.attachment, table.category),
                'office.msg_attachment_category_uniq')]

    @classmethod
    def __register__(cls, module_name):
        for old_table in [
                'brainbow_attachment-category',
                'brainbow_attachment-tag',
                'office_attachment-tag',
                ]:
            if (backend.TableHandler.table_exist(old_table)
                    and not backend.TableHandler.table_exist(cls._table)):
                backend.TableHandler.table_rename(old_table, cls._table)
        handler = cls.__table_handler__(module_name)
        if (handler.column_exist('tag')
                and not handler.column_exist('category')):
            handler.column_rename('tag', 'category')
        handler.drop_constraint('attachment_tag_uniq')
        super().__register__(module_name)
        cursor = Transaction().connection.cursor()
        relations = []
        table_name = 'brainbow_document-tag'
        if backend.TableHandler.table_exist(table_name):
            document = Table('brainbow_document')
            relation = Table(table_name)
            cursor.execute(*relation.join(document,
                    condition=document.id == relation.document).select(
                        document.attachment, relation.tag,
                        where=document.attachment != Null))
            relations.extend(cursor.fetchall())
        if backend.TableHandler.table_exist(
                'file_sync_tag_ir_attachment'):
            relation = Table('file_sync_tag_ir_attachment')
            cursor.execute(*relation.select(
                    relation.attachment, relation.tag))
            relations.extend(cursor.fetchall())
        for attachment, category in set(relations):
            if not cls.search([
                        ('attachment', '=', attachment),
                        ('category', '=', category),
                        ], limit=1):
                cls.create([{
                        'attachment': attachment,
                        'category': category,
                        }])


class CategoryReadOnlyGroup(ModelSQL):
    'Category - Read-only Group'
    __name__ = 'office.category-read-only-group'

    category = fields.Many2One(
        'office.category', 'Category', required=True, ondelete='CASCADE')
    group = fields.Many2One(
        'res.group', 'Group', required=True, ondelete='CASCADE')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('category')
        table = cls.__table__()
        cls._sql_constraints += [(
                'category_group_unique',
                Unique(table, table.category, table.group),
                'office.msg_category_group_unique')]

    @classmethod
    def __register__(cls, module_name):
        migrate_category_relation(
            cls, module_name,
            ['file_sync_category-read-only-group',
                'file_sync_tag-read-only-group'],
            'tag_group_unique')
        super().__register__(module_name)


class CategoryReadWriteGroup(ModelSQL):
    'Category - Read-write Group'
    __name__ = 'office.category-read-write-group'

    category = fields.Many2One(
        'office.category', 'Category', required=True, ondelete='CASCADE')
    group = fields.Many2One(
        'res.group', 'Group', required=True, ondelete='CASCADE')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('category')
        table = cls.__table__()
        cls._sql_constraints += [(
                'category_group_unique',
                Unique(table, table.category, table.group),
                'office.msg_category_group_unique')]

    @classmethod
    def __register__(cls, module_name):
        migrate_category_relation(
            cls, module_name,
            ['file_sync_category-read-write-group',
                'file_sync_tag-read-write-group'],
            'tag_group_unique')
        super().__register__(module_name)


class CategoryReadOnlyUser(ModelSQL):
    'Category - Read-only User'
    __name__ = 'office.category-read-only-user'

    category = fields.Many2One(
        'office.category', 'Category', required=True, ondelete='CASCADE')
    user = fields.Many2One(
        'res.user', 'User', required=True, ondelete='CASCADE')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('category')
        table = cls.__table__()
        cls._sql_constraints += [(
                'category_user_unique',
                Unique(table, table.category, table.user),
                'office.msg_category_user_unique')]

    @classmethod
    def __register__(cls, module_name):
        migrate_category_relation(
            cls, module_name,
            ['file_sync_category-read-only-user',
                'file_sync_tag-read-only-user'],
            'tag_user_unique')
        super().__register__(module_name)


class CategoryReadWriteUser(ModelSQL):
    'Category - Read-write User'
    __name__ = 'office.category-read-write-user'

    category = fields.Many2One(
        'office.category', 'Category', required=True, ondelete='CASCADE')
    user = fields.Many2One(
        'res.user', 'User', required=True, ondelete='CASCADE')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('category')
        table = cls.__table__()
        cls._sql_constraints += [(
                'category_user_unique',
                Unique(table, table.category, table.user),
                'office.msg_category_user_unique')]

    @classmethod
    def __register__(cls, module_name):
        migrate_category_relation(
            cls, module_name,
            ['file_sync_category-read-write-user',
                'file_sync_tag-read-write-user'],
            'tag_user_unique')
        super().__register__(module_name)
