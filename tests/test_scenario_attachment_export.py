import io
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from proteus import Model, launch_action
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestAttachmentExport(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')
        Attachment = Model.get('ir.attachment', config=config)

        with config.set_context(default_unlinked=True):
            markdown = Attachment(
                name='Guide', type='text',
                content='# Guide\n\nA **formatted** paragraph.')
            markdown.save()
            pdf = Attachment(
                name='existing.pdf', type='data', data=b'%PDF-original')
            pdf.save()

        extension, content, direct_print, name = launch_action(
            'office.report_attachment_pdf', [markdown], config=config)
        self.assertEqual(extension, 'pdf')
        self.assertTrue(content.startswith(b'%PDF'))
        self.assertFalse(direct_print)
        self.assertEqual(name, 'Guide')

        extension, content, _, _ = launch_action(
            'office.report_attachment_microsoft_office', [markdown],
            config=config)
        self.assertEqual(extension, 'docx')
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(content)))

        extension, content, _, _ = launch_action(
            'office.report_attachment_open_document', [markdown],
            config=config)
        self.assertEqual(extension, 'odt')
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(content)))

        extension, content, _, _ = launch_action(
            'office.report_attachment_pdf', [pdf], config=config)
        self.assertEqual(extension, 'pdf')
        self.assertEqual(content, b'%PDF-original')

        wizard = launch_action(
            'office.wizard_attachment_export', [markdown], config=config)
        wizard.form.format = 'rtf'
        wizard.execute('download')
        extension, content, _, _ = wizard.actions[0]
        self.assertEqual(extension, 'rtf')
        self.assertTrue(content.startswith(b'{\\rtf'))

        class Handler(BaseHTTPRequestHandler):

            def do_GET(self):
                body = b'Linked attachment content'
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', str(len(body)))
                self.send_header(
                    'Content-Disposition', 'attachment; filename=linked.txt')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format_, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with config.set_context(default_unlinked=True):
                link = Attachment(
                    name='Linked text.txt', type='link',
                    link='http://127.0.0.1:%s/file' % server.server_port)
                link.save()
            extension, content, _, _ = launch_action(
                'office.report_attachment_pdf', [link], config=config)
            self.assertEqual(extension, 'pdf')
            self.assertTrue(content.startswith(b'%PDF'))

            extension, content, _, _ = launch_action(
                'office.report_attachment_pdf', [markdown, link],
                config=config)
            self.assertEqual(extension, 'zip')
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    ['Guide.pdf', 'Linked text.pdf'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
