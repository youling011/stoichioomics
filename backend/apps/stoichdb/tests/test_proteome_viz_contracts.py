from django.test import SimpleTestCase
from backend.apps.stoichdb.proteome_viz.contracts import CORE_FIELDS,META,TITLES,ALIASES,SECTIONS

class ContractTests(SimpleTestCase):
    def test_complete_catalog_and_positions(self):
        self.assertEqual(len(set(CORE_FIELDS)),52);self.assertEqual(len(META),11);self.assertEqual(len(TITLES),31);self.assertEqual(len(SECTIONS['basic']),15);self.assertEqual(len(SECTIONS['analysis']),16);self.assertEqual(ALIASES,{'B10':'D02'})
