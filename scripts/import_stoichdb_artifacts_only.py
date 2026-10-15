from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings')

import django  # noqa: E402


django.setup()

from backend.apps.stoichdb.models import AnalysisArtifact, OmicsDataset, Species  # noqa: E402


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description='Import stage5 stoichdb artifacts without importing EntityRecord rows.')
    parser.add_argument('--stage5-root', required=True)
    parser.add_argument('--domain', default='Fungi')
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()

    stage5 = Path(args.stage5_root)
    if not stage5.exists():
        raise SystemExit(f'Missing stage5 root: {stage5}')

    species_map = {
        row.species_id: row
        for row in Species.objects.filter(domain=args.domain)
    }
    dataset_map = {
        (row.species.species_id, row.omics_type): row
        for row in OmicsDataset.objects.select_related('species').filter(species__domain=args.domain)
    }

    if args.replace:
        AnalysisArtifact.objects.filter(species__domain=args.domain).delete()

    records = []
    for species_id, species in species_map.items():
        species_dir = stage5 / species_id
        if not species_dir.exists():
            continue
        cross_path = species_dir / 'cross_omics.json'
        if cross_path.exists():
            records.append(AnalysisArtifact(
                artifact_id=f'{species_id}__cross_omics',
                species=species,
                dataset=None,
                omics_type='all',
                artifact_type='cross_omics',
                path=str(cross_path),
                payload_json=load_json(cross_path),
                version='v1',
            ))
        for omics in ['genome', 'transcriptome', 'proteome']:
            dataset = dataset_map.get((species_id, omics))
            if not dataset:
                continue
            for artifact_type in ['profile', 'core_features', 'summary', 'analysis']:
                path = species_dir / omics / f'{artifact_type}.json'
                if not path.exists():
                    continue
                records.append(AnalysisArtifact(
                    artifact_id=f'{species_id}__{omics}__{artifact_type}',
                    species=species,
                    dataset=dataset,
                    omics_type=omics,
                    artifact_type=artifact_type,
                    path=str(path),
                    payload_json=load_json(path),
                    version='v1',
                ))

    AnalysisArtifact.objects.bulk_create(records, batch_size=1000, ignore_conflicts=True)
    print(f'imported_artifacts {len(records)}')
    print(f'domain_artifacts {AnalysisArtifact.objects.filter(species__domain=args.domain).count()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
