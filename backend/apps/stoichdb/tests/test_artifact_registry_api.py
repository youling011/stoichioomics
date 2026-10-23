from unittest.mock import patch
from django.test import TestCase
from backend.apps.stoichdb.models import Species,AnalysisArtifact
from backend.apps.stoichdb import services

class ArtifactRegistryApiTests(TestCase):
    def setUp(self):
        self.species=Species.objects.create(species_id='artifact_limit_fixture',display_name='Artifact fixture')
        for i in range(3):
            AnalysisArtifact.objects.create(artifact_id=f'artifact_limit_{i}',species=self.species,omics_type='proteome',artifact_type='summary')
        for name,value in [('current_release',{}),('db_mode',True)]:
            context=patch.object(services,name,return_value=value);context.start();self.addCleanup(context.stop)
    def test_public_list_honors_limit_and_species(self):
        response=self.client.get('/api/stoichdb/downloads/artifacts/',{'limit':2,'species':self.species.species_id})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()['data']['items']),2)
        self.assertTrue(all(x['species_id']==self.species.species_id for x in response.json()['data']['items']))
    def test_invalid_limit_uses_view_default(self):
        response=self.client.get('/api/stoichdb/downloads/artifacts/',{'limit':'invalid','species':self.species.species_id})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()['data']['items']),3)
    def test_zero_limit_is_bounded_and_filters_still_apply(self):
        self.assertEqual(len(services.artifact_registry(species_id=self.species.species_id,limit=0)['items']),1)
        self.assertEqual(services.artifact_registry(species_id='missing',limit=1)['items'],[])

