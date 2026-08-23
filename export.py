import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from email.message import Message
from pathlib import Path
from urllib.error import URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import markdown

from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model import ModelView, fields
from trytond.pool import Pool
from trytond.report import Report
from trytond.wizard import Button, StateReport, StateView, Wizard


LIBREOFFICE_FORMATS = [
    ('apng', 'APNG - Animated Portable Network Graphics'),
    ('bmp', 'BMP - Bitmap Image'),
    ('csv', 'CSV - Comma-Separated Values'),
    ('dbf', 'DBF - dBASE'),
    ('dif', 'DIF - Data Interchange Format'),
    ('doc', 'DOC - Microsoft Word 97-2003'),
    ('docm', 'DOCM - Microsoft Word Macro-Enabled'),
    ('docx', 'DOCX - Microsoft Word'),
    ('dot', 'DOT - Microsoft Word 97-2003 Template'),
    ('dotm', 'DOTM - Microsoft Word Macro-Enabled Template'),
    ('dotx', 'DOTX - Microsoft Word Template'),
    ('dps', 'DPS - WPS Presentation'),
    ('dpt', 'DPT - WPS Presentation Template'),
    ('emf', 'EMF - Enhanced Metafile'),
    ('emz', 'EMZ - Compressed Enhanced Metafile'),
    ('eps', 'EPS - Encapsulated PostScript'),
    ('epub', 'EPUB - Electronic Publication'),
    ('et', 'ET - WPS Spreadsheet'),
    ('ett', 'ETT - WPS Spreadsheet Template'),
    ('fodg', 'FODG - Flat OpenDocument Drawing'),
    ('fodp', 'FODP - Flat OpenDocument Presentation'),
    ('fods', 'FODS - Flat OpenDocument Spreadsheet'),
    ('fodt', 'FODT - Flat OpenDocument Text'),
    ('gif', 'GIF - Graphics Interchange Format'),
    ('htm', 'HTM - Web Page'),
    ('html', 'HTML - Web Page'),
    ('jfif', 'JFIF - JPEG Image'),
    ('jif', 'JIF - JPEG Image'),
    ('jpe', 'JPE - JPEG Image'),
    ('jpeg', 'JPEG - JPEG Image'),
    ('jpg', 'JPG - JPEG Image'),
    ('mml', 'MML - MathML'),
    ('odc', 'ODC - OpenDocument Chart'),
    ('odf', 'ODF - OpenDocument Formula'),
    ('odg', 'ODG - OpenDocument Drawing'),
    ('odm', 'ODM - OpenDocument Master Document'),
    ('odp', 'ODP - OpenDocument Presentation'),
    ('ods', 'ODS - OpenDocument Spreadsheet'),
    ('odt', 'ODT - OpenDocument Text'),
    ('orp', 'ORP - OpenDocument Database Report'),
    ('otg', 'OTG - OpenDocument Drawing Template'),
    ('oth', 'OTH - HTML Document Template'),
    ('otm', 'OTM - OpenDocument Master Document Template'),
    ('otp', 'OTP - OpenDocument Presentation Template'),
    ('ots', 'OTS - OpenDocument Spreadsheet Template'),
    ('ott', 'OTT - OpenDocument Text Template'),
    ('pdf', 'PDF - Portable Document Format'),
    ('png', 'PNG - Portable Network Graphics'),
    ('pot', 'POT - Microsoft PowerPoint 97-2003 Template'),
    ('potm', 'POTM - Microsoft PowerPoint Macro-Enabled Template'),
    ('potx', 'POTX - Microsoft PowerPoint Template'),
    ('pps', 'PPS - Microsoft PowerPoint 97-2003 AutoPlay'),
    ('ppsx', 'PPSX - Microsoft PowerPoint AutoPlay'),
    ('ppt', 'PPT - Microsoft PowerPoint 97-2003'),
    ('pptm', 'PPTM - Microsoft PowerPoint Macro-Enabled'),
    ('pptx', 'PPTX - Microsoft PowerPoint'),
    ('rtf', 'RTF - Rich Text Format'),
    ('slk', 'SLK - SYLK Spreadsheet'),
    ('svg', 'SVG - Scalable Vector Graphics'),
    ('svgz', 'SVGZ - Compressed Scalable Vector Graphics'),
    ('sxw', 'SXW - OpenOffice.org 1.0 Text'),
    ('sylk', 'SYLK - SYLK Spreadsheet'),
    ('tab', 'TAB - Tab-Separated Values'),
    ('tif', 'TIF - Tagged Image File Format'),
    ('tiff', 'TIFF - Tagged Image File Format'),
    ('tsv', 'TSV - Tab-Separated Values'),
    ('txt', 'TXT - Plain Text'),
    ('webp', 'WEBP - WebP Image'),
    ('wmf', 'WMF - Windows Metafile'),
    ('wmz', 'WMZ - Compressed Windows Metafile'),
    ('wps', 'WPS - WPS Text Document'),
    ('wpt', 'WPT - WPS Text Document Template'),
    ('xhtml', 'XHTML - Extensible HTML'),
    ('xlc', 'XLC - Microsoft Excel Chart'),
    ('xlk', 'XLK - Microsoft Excel Backup'),
    ('xlm', 'XLM - Microsoft Excel Macro'),
    ('xls', 'XLS - Microsoft Excel 97-2003'),
    ('xlsm', 'XLSM - Microsoft Excel Macro-Enabled'),
    ('xlsx', 'XLSX - Microsoft Excel'),
    ('xlt', 'XLT - Microsoft Excel 97-2003 Template'),
    ('xltm', 'XLTM - Microsoft Excel Macro-Enabled Template'),
    ('xltx', 'XLTX - Microsoft Excel Template'),
    ('xlw', 'XLW - Microsoft Excel Workspace'),
    ('xml', 'XML'),
]

MICROSOFT_EXTENSIONS = {
    'doc', 'docm', 'docx', 'dot', 'dotm', 'dotx',
    'pot', 'potm', 'potx', 'pps', 'ppsm', 'ppsx', 'ppt', 'pptm', 'pptx',
    'xlc', 'xlk', 'xlm', 'xls', 'xlsb', 'xlsm', 'xlsx', 'xlt', 'xltm',
    'xltx', 'xlw',
}
OPEN_DOCUMENT_EXTENSIONS = {
    'fodg', 'fodp', 'fods', 'fodt', 'odc', 'odf', 'odg', 'odm', 'odp',
    'ods', 'odt', 'orp', 'otg', 'oth', 'otm', 'otp', 'ots', 'ott',
}
SPREADSHEET_EXTENSIONS = {
    'csv', 'dbf', 'dif', 'et', 'ett', 'fods', 'ods', 'ots', 'slk', 'sylk',
    'tab', 'tsv', 'xlc', 'xlk', 'xlm', 'xls', 'xlsb', 'xlsm', 'xlsx',
    'xlt', 'xltm', 'xltx', 'xlw',
}
PRESENTATION_EXTENSIONS = {
    'dps', 'dpt', 'fodp', 'odp', 'otp', 'pot', 'potm', 'potx',
    'pps', 'ppsm', 'ppsx', 'ppt', 'pptm', 'pptx',
}
DRAWING_EXTENSIONS = {
    'apng', 'bmp', 'emf', 'emz', 'eps', 'fodg', 'gif', 'jfif', 'jif',
    'jpe', 'jpg', 'jpeg', 'odg', 'otg', 'png', 'svg', 'svgz', 'tif',
    'tiff', 'webp', 'wmf', 'wmz',
}
MAX_LINK_SIZE = 100 * 1024 * 1024


def _extension(filename):
    extension = Path(filename or '').suffix.lower().lstrip('.')
    return {'jpeg': 'jpg', 'tif': 'tiff'}.get(extension, extension)


def _output_extension(source_extension, family):
    if family == 'pdf':
        return 'pdf'
    if family == 'microsoft':
        if source_extension in MICROSOFT_EXTENSIONS:
            return source_extension
        if source_extension in SPREADSHEET_EXTENSIONS:
            return 'xlsx'
        if source_extension in PRESENTATION_EXTENSIONS:
            return 'pptx'
        return 'docx'
    if source_extension in OPEN_DOCUMENT_EXTENSIONS:
        return source_extension
    if source_extension in SPREADSHEET_EXTENSIONS:
        return 'ods'
    if source_extension in PRESENTATION_EXTENSIONS:
        return 'odp'
    if source_extension in DRAWING_EXTENSIONS:
        return 'odg'
    return 'odt'


def _markdown_html(content):
    body = markdown.markdown(
        content or '', output_format='xhtml',
        extensions=['fenced_code', 'tables'])
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>body{font-family:sans-serif;line-height:1.5;max-width:50em;'
        'margin:2em auto;padding:0 1em}pre{white-space:pre-wrap}table{border-'
        'collapse:collapse}td,th{border:1px solid #aaa;padding:.35em}</style>'
        f'</head><body>{body}</body></html>').encode('utf-8')


def _download_link(attachment):
    parsed = urlparse(attachment.link or '')
    if parsed.scheme not in {'http', 'https'}:
        raise UserError(gettext('office.msg_invalid_attachment_link'))
    request = Request(attachment.link, headers={
            'User-Agent': 'Tryton Office attachment converter',
            })
    try:
        with urlopen(request, timeout=30) as response:
            length = response.headers.get('Content-Length')
            if length and int(length) > MAX_LINK_SIZE:
                raise UserError(gettext(
                        'office.msg_attachment_link_too_large'))
            content = response.read(MAX_LINK_SIZE + 1)
            if len(content) > MAX_LINK_SIZE:
                raise UserError(gettext(
                        'office.msg_attachment_link_too_large'))
            disposition = Message()
            disposition['Content-Disposition'] = response.headers.get(
                'Content-Disposition', '')
            filename = disposition.get_filename()
            if not filename:
                filename = Path(unquote(urlparse(response.url).path)).name
    except (OSError, URLError, ValueError) as exception:
        raise UserError(gettext(
                'office.msg_attachment_link_download_failed',
                error=str(exception))) from exception
    return content, filename or attachment.name or 'attachment'


def _attachment_content(attachment):
    if attachment.type == 'text':
        return _markdown_html(attachment.content), 'attachment.html', True
    if attachment.type == 'link':
        content, filename = _download_link(attachment)
        return content, filename, False
    if not attachment.data:
        raise UserError(gettext(
                'office.msg_attachment_without_data',
                attachment=attachment.rec_name))
    return bytes(attachment.data), attachment.name or 'attachment', False


def _convert_with_soffice(content, filename, output_extension):
    executable = shutil.which('soffice')
    if not executable:
        raise UserError(gettext('office.msg_soffice_not_found'))
    with tempfile.TemporaryDirectory(prefix='office-convert-') as directory:
        directory = Path(directory)
        source = directory / Path(filename).name
        source.write_bytes(content)
        profile = directory / 'profile'
        command = [
            executable, '--headless',
            f'-env:UserInstallation={profile.as_uri()}',
        ]
        if _extension(filename) in {'html', 'xhtml'}:
            command.append('--infilter=HTML (StarWriter)')
        command.extend([
                '--convert-to', output_extension,
                '--outdir', str(directory), str(source),
                ])
        try:
            process = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=False, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as exception:
            raise UserError(gettext(
                    'office.msg_attachment_conversion_failed',
                    error=str(exception))) from exception
        output = directory / f'{source.stem}.{output_extension}'
        if process.returncode or not output.is_file():
            detail = process.stdout.decode('utf-8', errors='replace').strip()
            raise UserError(gettext(
                    'office.msg_attachment_conversion_failed',
                    error=detail or str(process.returncode)))
        return output.read_bytes()


def _convert_attachment(attachment, output_extension=None, family=None):
    content, filename, markdown_source = _attachment_content(attachment)
    source_extension = _extension(filename)
    if family:
        output_extension = _output_extension(source_extension, family)
    if not markdown_source and source_extension == output_extension:
        return content, filename
    if markdown_source and output_extension in {'html', 'xhtml'}:
        return content, (
            f'{Path(attachment.name or "attachment").stem}.{output_extension}')
    if markdown_source and output_extension == 'txt':
        return (attachment.content or '').encode('utf-8'), (
            f'{Path(attachment.name or "attachment").stem}.txt')
    if markdown_source and output_extension == 'pdf':
        try:
            from weasyprint import HTML
        except ImportError:
            pass
        else:
            return HTML(string=content.decode('utf-8')).write_pdf(), (
                f'{Path(attachment.name or "attachment").stem}.pdf')
    converted = _convert_with_soffice(content, filename, output_extension)
    name = Path(attachment.name or filename or 'attachment').stem
    return converted, f'{name}.{output_extension}'


class AttachmentExportReport(Report):
    family = None

    @classmethod
    def get_output_extension(cls, attachment, data):
        return None

    @classmethod
    def execute(cls, ids, data):
        pool = Pool()
        ActionReport = pool.get('ir.action.report')
        Attachment = pool.get('ir.attachment')
        action_id = data.get('action_id')
        if action_id:
            action = ActionReport(action_id)
        else:
            action, = ActionReport.search([
                    ('report_name', '=', cls.__name__),
                    ], limit=1)
        cls.check_access(action, action.model or data.get('model'), ids)
        attachments = Attachment.browse(ids)
        if not attachments:
            raise UserError(gettext('office.msg_no_attachments_selected'))
        files = []
        for attachment in attachments:
            output_extension = cls.get_output_extension(attachment, data)
            content, filename = _convert_attachment(
                attachment, output_extension, cls.family)
            files.append((filename, content))
        if len(files) == 1:
            filename, content = files[0]
            return _extension(filename), content, False, Path(filename).stem
        archive = io.BytesIO()
        names = set()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
            for filename, content in files:
                filename = os.path.basename(filename)
                stem = Path(filename).stem
                suffix = Path(filename).suffix
                unique_name = filename
                sequence = 2
                while unique_name in names:
                    unique_name = f'{stem}-{sequence}{suffix}'
                    sequence += 1
                names.add(unique_name)
                output.writestr(unique_name, content)
        return 'zip', archive.getvalue(), False, 'attachments'


class AttachmentPDF(AttachmentExportReport):
    __name__ = 'office.attachment.pdf'
    family = 'pdf'


class AttachmentMicrosoftOffice(AttachmentExportReport):
    __name__ = 'office.attachment.microsoft_office'
    family = 'microsoft'


class AttachmentOpenDocument(AttachmentExportReport):
    __name__ = 'office.attachment.open_document'
    family = 'open_document'


class AttachmentExportStart(ModelView):
    'Attachment Export Start'
    __name__ = 'office.attachment.export.start'

    format = fields.Selection(
        'get_formats', 'Output Format', required=True, sort=False)

    @staticmethod
    def get_formats():
        return LIBREOFFICE_FORMATS

    @staticmethod
    def default_format():
        return 'pdf'


class AttachmentExport(Wizard):
    'Attachment Export'
    __name__ = 'office.attachment.export'

    start = StateView(
        'office.attachment.export.start',
        'office.attachment_export_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Download', 'download', 'tryton-download', default=True),
        ])
    download = StateReport('office.attachment.custom')

    def do_download(self, action):
        return action, {
            'ids': [record.id for record in self.records],
            'format': self.start.format,
        }


class AttachmentCustom(AttachmentExportReport):
    __name__ = 'office.attachment.custom'

    @classmethod
    def get_output_extension(cls, attachment, data):
        output_extension = data.get('format')
        if output_extension not in dict(LIBREOFFICE_FORMATS):
            raise UserError(gettext('office.msg_invalid_output_format'))
        return output_extension
