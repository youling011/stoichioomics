from unittest import TestCase
from backend.apps.stoichdb.sequence_viz.api import presentation
class EmptyScientificViews(TestCase):
    def view(self,data):return presentation({'chart_id':'GD13','title':'old','status':'available','data':data},{'available_scopes':['core','full']})
    def test_all_missing_distribution_is_unavailable(self):self.assertEqual(self.view({'profile':{'n_valid':0}})['status'],'unavailable')
    def test_mixed_valid_profiles_preserve_available_information(self):self.assertEqual(self.view({'profiles':[{'n_valid':0},{'n_valid':8}]})['status'],'partial')
    def test_real_zero_point_mass_remains_available(self):self.assertEqual(self.view({'profile':{'n_valid':8,'n_zero':8,'histogram':{'kind':'point_mass'}}})['status'],'available')
    def test_no_pairs_or_candidates_never_claim_available(self):
        self.assertEqual(self.view({'hex':{'n':0}})['status'],'unavailable')
        self.assertEqual(self.view({'kind':'native_candidate_evidence','rows':[]})['status'],'unavailable')
    def test_aggregate_export_matches_public_empty_state_and_title(self):
        import json
        from unittest.mock import patch
        from django.http import JsonResponse
        from rest_framework.test import APIRequestFactory
        from backend.apps.stoichdb.sequence_viz.api import export_view
        manifest={'available_scopes':['core','full']};figure={'chart_id':'GD13','title':'old','status':'available','data':{'profile':{'n_valid':0}}}
        with patch('backend.apps.stoichdb.sequence_viz.api.target',return_value=('unused',manifest)),patch('backend.apps.stoichdb.sequence_viz.api.store.bundle',return_value={'GD13':figure}),patch('backend.apps.stoichdb.sequence_viz.api.download',return_value=JsonResponse(figure)):
            result=export_view(APIRequestFactory().get('/',{'kind':'chart','chart_id':'GD13'}),'example','genome')
        self.assertEqual(result.status_code,200)
        self.assertEqual(json.loads(result.content),presentation(figure,manifest))
