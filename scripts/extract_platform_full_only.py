"""Platform source ingestion wrapper; independent extractor CLIs stay intact."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path as NativePath
PROJECT=NativePath(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.config.settings')
from backend.apps.common.host_paths import Path
from backend.apps.stoichdb.feature_sources.provenance import frozen_provenance
from backend.apps.stoichdb.feature_sources.registration import require_source_root
from backend.apps.stoichdb.feature_sources.new_sources import prepare

def command_for(omics,extractor,full_path,extra,python):
    forbidden={'--feature-set','--emit','--out','--out-full','--out-core','--out-dir','--batch-dir','--batch-manifest','--manifest','--append','--schema-out'}
    if any(token.split('=',1)[0] in forbidden for token in extra):raise ValueError('The platform wrapper controls output/scope; pass scientific input options only')
    command=[python,'-B',str(extractor),*extra,'--feature-set','full','--out',str(full_path)]
    if omics=='genome' and '--include-exon' not in extra:command.append('--include-exon')
    return command

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--omics',required=True,choices=['genome','transcriptome','proteome'])
    parser.add_argument('--full-output',required=True);parser.add_argument('--core-alias',required=True)
    parser.add_argument('--recipe-catalog',required=True);parser.add_argument('--recipe-id',required=True)
    parser.add_argument('--dataset-id',required=True);parser.add_argument('--bindings-out',required=True)
    parser.add_argument('--extractor-root',default=r'G:\stoichioomics\项目平台数据\组学化学计量特征提取代码')
    parser.add_argument('--python',default=sys.executable);parser.add_argument('--run',action='store_true')
    parser.add_argument('extractor_args',nargs=argparse.REMAINDER)
    args=parser.parse_args();full=Path(args.full_output);core=Path(args.core_alias);out=Path(args.bindings_out)
    require_source_root(full);require_source_root(core)
    if full.exists() or core.exists() or out.exists():raise ValueError('New-version output paths must not replace any existing source or report')
    provenance=frozen_provenance();original=provenance['extractors'][args.omics]
    extractor=Path(args.extractor_root)/original['filename']
    if hashlib.sha256(extractor.read_bytes()).hexdigest()!=original['sha256']:raise ValueError('Extractor code drift requires review and a new proven recipe')
    catalog=json.loads(Path(args.recipe_catalog).read_text(encoding='utf-8'));recipes=catalog.get('recipes',catalog)
    recipe=recipes[args.recipe_id]
    if recipe['omics_type']!=args.omics:raise ValueError('Frozen recipe omics differs')
    extra=args.extractor_args[1:] if args.extractor_args[:1]==['--'] else args.extractor_args
    command=command_for(args.omics,extractor,full,extra,args.python)
    if not args.run:
        print(json.dumps({'apply':False,'command':command,'core_alias':str(core),'core_source_will_be_created':False},ensure_ascii=False));return
    full.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(command,check=True)
    if core.exists():raise RuntimeError('Extractor unexpectedly created the platform Core source; import blocked')
    manifest=prepare(full,core,args.omics,args.recipe_id,recipe,args.dataset_id)
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8') as handle:json.dump(manifest,handle,ensure_ascii=False,separators=(',',':'))
    print('Full-only source and audited logical Core manifest prepared; use the normal registry/import pipeline with this manifest.')

if __name__=='__main__':main()
