from trytond.pool import Pool

from . import ai
from . import attachment
from . import document
from . import export


def register():
    Pool.register(
        ai.AIConfiguration,
        attachment.Index,
        attachment.Category,
        attachment.Unlinked,
        attachment.Attachment,
        attachment.AttachmentReaderGroup,
        attachment.AttachmentWriterGroup,
        attachment.AttachmentCategory,
        attachment.AttachmentCategoryUnion,
        attachment.CategoryReadOnlyGroup,
        attachment.CategoryReadWriteGroup,
        attachment.CategoryReadOnlyUser,
        attachment.CategoryReadWriteUser,
        document.Configuration,
        document.DocumentTemplate,
        document.DocumentCreateStart,
        export.AttachmentExportStart,
        module='office', type_='model')
    Pool.register(
        export.AttachmentPDF,
        export.AttachmentMicrosoftOffice,
        export.AttachmentOpenDocument,
        export.AttachmentCustom,
        module='office', type_='report')
    Pool.register(
        attachment.AttachmentCategoryOpen,
        export.AttachmentExport,
        document.DocumentCreate,
        module='office', type_='wizard')
