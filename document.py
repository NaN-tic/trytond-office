import base64
import mimetypes
from pathlib import Path

from trytond.model import (
    DeactivableMixin, ModelSingleton, ModelSQL, ModelView, fields)
from trytond.pool import Pool
from trytond.pyson import Bool, Eval
from trytond.wizard import Button, StateAction, StateTransition, StateView, Wizard


class Configuration(ModelSingleton, ModelSQL, ModelView):
    'Office Configuration'
    __name__ = 'office.configuration'

    default_filename = fields.Char('Default Filename', required=True)

    @staticmethod
    def default_default_filename():
        return 'unnamed document'


class DocumentTemplate(DeactivableMixin, ModelSQL, ModelView):
    'Document Template'
    __name__ = 'office.document.template'

    name = fields.Char('Name', required=True, translate=True)
    mime_type = fields.Char('MIME Type', required=True)
    extension = fields.Char('Extension', required=True)
    type = fields.Selection([
            ('link', 'Link'),
            ('data', 'Data'),
            ('text', 'Text'),
            ], 'Type', required=True)
    data = fields.Binary('File', states={
            'invisible': Eval('type') != 'data',
            }, depends=['type'])
    url = fields.Char('URL', states={
            'invisible': Eval('type') != 'link',
            }, depends=['type'])
    content = fields.Text('Content', states={
            'invisible': Eval('type') != 'text',
            }, depends=['type'])

    @staticmethod
    def default_type():
        return 'data'

    @fields.depends('extension')
    def on_change_extension(self):
        self.extension = self.normalize_extension(self.extension)
        if self.extension:
            self.mime_type = mimetypes.guess_type(
                f'file.{self.extension}', strict=False)[0]
        else:
            self.mime_type = None

    @classmethod
    def create(cls, vlist):
        vlist = [values.copy() for values in vlist]
        for values in vlist:
            if 'extension' in values:
                values['extension'] = cls.normalize_extension(
                    values['extension'])
            data = values.get('data')
            if isinstance(data, str) and data.startswith('base64:'):
                values['data'] = base64.b64decode(
                    data.removeprefix('base64:'), validate=True)
        return super().create(vlist)

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        new_args = []
        for records, values in zip(actions, actions):
            values = values.copy()
            if 'extension' in values:
                values['extension'] = cls.normalize_extension(
                    values['extension'])
            new_args.extend([records, values])
        super().write(*new_args)

    @staticmethod
    def normalize_extension(extension):
        return (extension or '').strip().lstrip('.').lower()

    def filename(self, filename):
        extension = self.normalize_extension(self.extension)
        filename = filename or ''
        suffix = Path(filename).suffix
        if suffix:
            filename = filename[:-len(suffix)]
        return f'{filename}.{extension}'

    def attachment_values(
            self, filename, categories, unlinked, resource,
            current_categories=()):
        category_values = []
        if current_categories:
            category_values.append(
                ('remove', [category.id for category in current_categories]))
        if categories:
            category_values.append(
                ('add', [category.id for category in categories]))
        values = {
            'name': self.filename(filename),
            'type': self.type,
            'mimetype': self.mime_type,
            'categories': category_values,
            'unlinked': unlinked,
            'resource': str(resource) if resource else None,
            }
        if self.type == 'data':
            values.update(data=self.data, link=None, content=None)
        elif self.type == 'link':
            values.update(data=None, link=self.url, content=None)
        else:
            values.update(data=None, link=None, content=self.content)
        return values


class DocumentCreateStart(ModelView):
    'Create Document from Template'
    __name__ = 'office.document.create.start'

    template = fields.Many2One(
        'office.document.template', 'Template', required=True)
    filename = fields.Char('Filename', required=True)
    categories = fields.Many2Many(
        'office.category', None, None, 'Categories',
        domain=[('view', '=', False)])
    unlinked = fields.Boolean('Unlinked')
    resource = fields.Reference(
        'Resource', selection='get_resources', states={
            'invisible': Bool(Eval('unlinked')),
            'required': ~Bool(Eval('unlinked')),
            }, depends=['unlinked'])

    @staticmethod
    def get_resources():
        return Pool().get('ir.attachment').get_models()

    @classmethod
    def default_template(cls):
        Template = Pool().get('office.document.template')
        templates = Template.search([], limit=2)
        if len(templates) == 1:
            return templates[0].id

    @fields.depends('template', 'filename')
    def on_change_template(self):
        if self.template:
            self.filename = self.template.filename(self.filename)

    @fields.depends('unlinked', 'resource')
    def on_change_unlinked(self):
        if self.unlinked:
            self.resource = None


class DocumentCreate(Wizard):
    'Create Document from Template'
    __name__ = 'office.document.create'

    start = StateView(
        'office.document.create.start',
        'office.document_create_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Create', 'create_', 'tryton-ok', default=True),
            ])
    create_ = StateTransition()
    open_ = StateAction('office.action_attachment_created')

    def default_start(self, fields):
        Attachment = Pool().get('ir.attachment')
        defaults = {
            'filename': Attachment.default_name(),
            'unlinked': True,
            }
        if self.record and self.record.__name__ == 'ir.attachment':
            defaults.update({
                    'filename': self.record.name,
                    'categories': [
                        category.id for category in self.record.categories],
                    'unlinked': self.record.unlinked,
                    'resource': (str(self.record.resource)
                        if not self.record.unlinked else None),
                    })
        return defaults

    def transition_create_(self):
        Attachment = Pool().get('ir.attachment')
        values = self.start.template.attachment_values(
            self.start.filename, self.start.categories,
            self.start.unlinked, self.start.resource,
            (self.record.categories
                if self.record and self.record.__name__ == 'ir.attachment'
                else ()))
        if self.record and self.record.__name__ == 'ir.attachment':
            Attachment.write([self.record], values)
            self.attachment = self.record
        else:
            self.attachment, = Attachment.create([values])
        if self.record and self.record.__name__ == 'ir.attachment':
            return 'end'
        return 'open_'

    def do_open_(self, action):
        return action, {'res_id': self.attachment.id}
