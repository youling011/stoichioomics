from pathlib import Path
import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from backend.apps.stoichdb.compare_core.catalog import catalog
from backend.apps.stoichdb.compare_core.contracts import atomic_json, OMICS, file_sha
from backend.apps.stoichdb.compare_core.profiles import get_profile
from backend.apps.stoichdb.compare_core.sources import resolve, signature


class Command(BaseCommand):
    help = 'Independently recompute every numeric Core field from real files using a separate Pandas path.'

    def add_arguments(self, parser):
        parser.add_argument('--species-ids', required=True)
        parser.add_argument('--independent', action='store_true')
        parser.add_argument('--out', required=True)

    def handle(self, *args, **options):
        checks, failures, source_hashes = [], [], []
        cat = catalog()
        for sid in options['species_ids'].split(','):
            for o in OMICS:
                profile = get_profile(sid, o, cat)
                source, _, _, _ = resolve(sid, o)
                before = signature(source.path)
                content_sha256 = file_sha(source.path)
                frame = pd.read_csv(source.path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
                if before != signature(source.path) or content_sha256 != profile['content_sha256']:
                    raise CommandError(f'Source snapshot changed: {sid}/{o}')
                source_hashes.append({'species_id': sid, 'omics': o, 'content_sha256': content_sha256,
                                      'matches_profile': True, 'n_source': len(frame)})
                for field in profile['fields']:
                    name = field['field']
                    if field['compare_role'] not in ('numeric', 'composition', 'binary_summary') or name not in frame:
                        continue
                    raw = frame[name].astype(str).str.strip()
                    app = pd.Series(True, index=frame.index)
                    for dep, operator, threshold in field['applicability_rule']:
                        if dep not in frame:
                            app[:] = True
                            break
                        numeric_dep = pd.to_numeric(frame[dep], errors='coerce')
                        app &= numeric_dep.eq(threshold) if operator == 'eq' else numeric_dep.gt(threshold)
                    parsed = pd.to_numeric(raw.replace({'True': '1', 'False': '0', 'true': '1', 'false': '0'}) if field['compare_role'] == 'binary_summary' else raw, errors='coerce')
                    valid = app & np.isfinite(parsed)
                    if field['bounded_min'] is not None:
                        valid &= parsed.ge(field['bounded_min'])
                    if field['bounded_max'] is not None:
                        valid &= parsed.le(field['bounded_max'])
                    if field['compare_role'] == 'binary_summary':
                        valid &= parsed.isin([0, 1])
                    arr = parsed[valid].to_numpy(float)
                    expected = {'n_valid': len(arr), 'n_zero': int((arr == 0).sum())}
                    if len(arr):
                        expected.update(mean=float(arr.mean()), population_std=float(arr.std()), median=float(np.quantile(arr, .5)),
                            p10=float(np.quantile(arr, .1)), p25=float(np.quantile(arr, .25)), p75=float(np.quantile(arr, .75)), p90=float(np.quantile(arr, .9)))
                    for key, value in expected.items():
                        actual = field.get(key)
                        passed = actual is not None and (actual == value if key.startswith('n_') else np.isclose(actual, value, atol=1e-8, rtol=1e-8))
                        if not passed:
                            failures.append({'species_id': sid, 'field_key': field['field_key'], 'stat': key, 'actual': actual, 'expected': value})
                    invariant = field['n_source'] == field['n_applicable'] + field['n_structural_na'] and field['n_applicable'] == sum(field[k] for k in ('n_valid', 'n_missing', 'n_nonfinite', 'n_invalid'))
                    if not invariant:
                        failures.append({'species_id': sid, 'field_key': field['field_key'], 'reason': 'count_invariant'})
                    checks.append({'species_id': sid, 'field_key': field['field_key'], 'n_valid': len(arr)})
                self.stdout.write(f'{sid}/{o}: independently checked')
        atomic_json(Path(options['out']), {'independent': True, 'fields_checked': len(checks), 'source_hashes': source_hashes,
            'failures': failures, 'checks': checks, 'status': 'passed' if not failures else 'failed'})
        if failures:
            raise CommandError(f'{len(failures)} independent comparisons failed.')
        self.stdout.write(f'{len(checks)} field profiles independently verified.')
