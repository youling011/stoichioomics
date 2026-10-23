from pathlib import Path
import sys,os,json,argparse,importlib.metadata as im
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.config.settings')
import django;django.setup()
from django.conf import settings
from django.db import connection
from backend.apps.hvg.research_repository import readonly_source
from backend.apps.stoichdb.models import FunctionalAnnotationRelease,OmicsDataset,GOAnnotation,KEGGAnnotationLink
from backend.analysis_engine.hvg_research.artifacts import atomic_json,digest
def main():
 p=argparse.ArgumentParser();p.add_argument('--species-id',default='arabidopsis_thaliana');p.add_argument('--report',required=True);a=p.parse_args()
 with readonly_source():
  with connection.cursor() as c:c.execute('SHOW server_version');version=c.fetchone()[0]
  report={'database_engine':'postgresql','server_version':version,'readonly_source':True,'research_creation_enabled':settings.HVG_RESEARCH_ENABLED,'species_id':a.species_id,'annotation_releases':list(FunctionalAnnotationRelease.objects.filter(is_active=True).values_list('release_id',flat=True)),'datasets':list(OmicsDataset.objects.filter(species__species_id=a.species_id).values('dataset_id','omics_type','schema_version','row_count_core')),'go_rows':GOAnnotation.objects.filter(species_id_text=a.species_id).count(),'kegg_rows':KEGGAnnotationLink.objects.filter(species_id_text=a.species_id).count(),'registry_sha256':digest(Path(settings.BASE_DIR)/'shared/schemas/stoich_ml_feature_registry_v1.json'),'versions':{n:im.version(n) for n in ['Django','scanpy','anndata','numpy','scipy','pandas','statsmodels','gseapy','pyarrow']}}
 atomic_json(Path(a.report),report);connection.close();print('Read-only environment audit saved')
if __name__=='__main__':main()
