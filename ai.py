from trytond.model import fields
from trytond.pool import PoolMeta


class AIConfiguration(metaclass=PoolMeta):
    __name__ = 'ai.configuration'

    office_title_model = fields.Many2One(
        'ai.model', 'Office Title Model',
        domain=[('type', '=', 'llm')], ondelete='RESTRICT')
    office_language_model = fields.Many2One(
        'ai.model', 'Office Language Model',
        domain=[('type', '=', 'llm')], ondelete='RESTRICT')

    @classmethod
    def __register__(cls, module_name):
        handler = cls.__table_handler__(module_name)
        if (handler.column_exist('brainbow_title_model')
                and not handler.column_exist('office_title_model')):
            handler.column_rename(
                'brainbow_title_model', 'office_title_model')
        if (handler.column_exist('brainbow_language_model')
                and not handler.column_exist('office_language_model')):
            handler.column_rename(
                'brainbow_language_model', 'office_language_model')
        super().__register__(module_name)
