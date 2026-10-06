import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import run

class SettingsTests(unittest.TestCase):
    def test_environment_works_without_settings_file(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'LOCAL_MODEL':'test-model'},clear=True):
            self.assertEqual(run.env_settings(Path(folder)/'missing.env'),{'LOCAL_MODEL':'test-model'})
    def test_environment_overrides_file_and_bom_is_supported(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'LOCAL_MODEL':'env-model'},clear=True):
            p=Path(folder)/'settings.env'
            p.write_text('# example\nLOCAL_MODEL=file-model\nBAR_DATA_DIR="C:/Games/BAR/data"\n',encoding='utf-8-sig')
            cfg=run.env_settings(p)
            self.assertEqual(cfg['LOCAL_MODEL'],'env-model')
            self.assertEqual(run.configured_data(cfg),Path('C:/Games/BAR/data'))
    def test_blank_install_path_keeps_existing_default(self):
        self.assertEqual(run.configured_data({'BAR_DATA_DIR':' '}),run.DATA)

if __name__=='__main__':unittest.main()
