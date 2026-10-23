import json
from unittest.mock import patch
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory
from backend.apps.stoichdb.sequence_viz.api import export_view

class CohortExportSelection(SimpleTestCase):
    def check_selection(self,query,expected):
        with patch('backend.apps.stoichdb.sequence_viz.api.target',return_value=('unused',{})),patch('backend.apps.stoichdb.sequence_viz.cohorts.compute',return_value={'selected_species':expected}) as compute:
            response=export_view(APIRequestFactory().get('/',{'kind':'cohort',**query}),'example','genome')
            self.assertEqual(response.status_code,200)
            self.assertEqual(compute.call_args.args[3],expected)
            self.assertEqual(json.loads(response.content)['selected_species'],expected)
    def test_explicit_empty_stays_empty_in_export(self):self.check_selection({'species':''},[])
    def test_omitted_selection_uses_default(self):self.check_selection({},None)
    def test_duplicate_and_empty_entries_follow_chart_selection(self):self.check_selection({'species':'a,,b,a'},['a','b'])
