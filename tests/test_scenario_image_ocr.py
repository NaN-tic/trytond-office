from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestImageOCR(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('office')

        with Transaction().start(
                config.database_name, config.user,
                context=config.context) as transaction:
            pool = Pool(config.database_name)
            AIModel = pool.get('ai.model')
            Attachment = pool.get('ir.attachment')
            IRConfiguration = pool.get('ir.configuration')
            Lang = pool.get('ir.lang')
            OfficeConfiguration = pool.get('office.configuration')
            english, = Lang.search([('code', '=', 'en')])
            model, = AIModel.create([{
                        'name': 'Vision model',
                        'model_name': 'example/vision',
                        'provider': 'openai',
                        'type': 'llm',
                        }])
            image_values = {
                'name': 'scan.png',
                'type': 'data',
                'data': b'image data',
                'mimetype': 'image/png',
                'unlinked': True,
                }
            with Transaction().set_context(office_migration=True):
                unconfigured, configured, localized, extracted, document = (
                    Attachment.create([
                            image_values,
                            image_values,
                            image_values | {'language': english.id},
                            image_values,
                            {
                                'name': 'empty.pdf',
                                'type': 'data',
                                'data': b'document data',
                                'mimetype': 'application/pdf',
                                'unlinked': True,
                                },
                            ]))

            converter = MagicMock()
            converter.convert.return_value.text_content = ''
            with (
                    patch(
                        'trytond.modules.office.attachment.MarkItDown',
                        return_value=converter),
                    patch.object(AIModel, 'get_completion') as completion):
                Attachment.extract_content([unconfigured])
                completion.assert_not_called()

                OfficeConfiguration.write(
                    [OfficeConfiguration(1)], {'image_ocr_model': model.id})
                IRConfiguration.write(
                    [IRConfiguration(1)], {'language': 'ca'})
                completion.return_value = (SimpleNamespace(choices=[
                            SimpleNamespace(message=SimpleNamespace(
                                    content=(
                                        '{"literal_text": "# Invoice 42\\n\\n'
                                        '- Total: 42", '
                                        '"description": "A scanned invoice"}'))),
                            ]), False)
                Attachment.extract_content([configured])
                self.assertEqual(
                    configured.content, '# Invoice 42\n\n- Total: 42')
                self.assertEqual(
                    configured.description, 'A scanned invoice')
                completion.assert_called_once()
                messages = completion.call_args.args[0]
                self.assertIn('literal_text', messages[0]['content'])
                self.assertIn('description', messages[0]['content'])
                self.assertIn('Markdown syntax', messages[0]['content'])
                self.assertIn('(ca)', messages[0]['content'])
                self.assertEqual(messages[1]['role'], 'user')
                self.assertEqual(
                    messages[1]['content'][0]['type'], 'image_url')
                self.assertEqual(completion.call_args.args[1], configured)

                completion.reset_mock()
                Attachment.extract_content([localized])
                messages = completion.call_args.args[0]
                self.assertIn('(en)', messages[0]['content'])

                completion.reset_mock()
                converter.convert.return_value.text_content = 'From MarkItDown'
                Attachment.extract_content([extracted])
                self.assertEqual(extracted.content, 'From MarkItDown')
                completion.assert_not_called()

                converter.convert.return_value.text_content = ''
                Attachment.extract_content([document])
                self.assertEqual(document.content, '')
                completion.assert_not_called()
            transaction.commit()
