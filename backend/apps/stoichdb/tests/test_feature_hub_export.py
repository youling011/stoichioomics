import csv
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from django.test import SimpleTestCase

from backend.apps.stoichdb.feature_hub import export as feature_export


class FeatureHubExportPackagingTests(SimpleTestCase):
    def test_ml_export_writes_plain_csv_files_inside_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_id = "fh_test_plain_csv"
            request_payload = {
                "export_id": export_id,
                "species_ids": ["species_a"],
                "omics": "genome",
                "scope": "core",
                "mode": "ml_package",
                "fields": ["feature_a", "feature_b"],
                "metadata_fields": ["gene_id"],
            }
            source = SimpleNamespace(
                dataset_id="species_a__genome",
                path=tmp_path / "source.core.csv",
                file_size=123,
                schema_version="test_schema",
                fingerprint="source_fingerprint",
                warnings=[],
            )

            with (
                patch.object(feature_export, "EXPORT_ROOT", tmp_path / "exports"),
                patch.object(
                    feature_export,
                    "split_x_metadata",
                    return_value={
                        "x_fields": ["feature_a", "feature_b"],
                        "metadata_fields": ["gene_id"],
                        "excluded_from_x": [],
                        "preprocessing_recipe": {"fit_scope": "train_fold_only"},
                    },
                ),
                patch.object(feature_export, "DatasetSourceResolver") as resolver_cls,
                patch.object(
                    feature_export,
                    "iter_rows",
                    return_value=[
                        {"feature_a": "1.2", "feature_b": "3.4", "gene_id": "gene-1"},
                        {"feature_a": "5.6", "feature_b": "7.8", "gene_id": "gene-2"},
                    ],
                ),
                patch.object(feature_export, "qc_report", return_value={"status": "ok"}),
                patch.object(
                    feature_export,
                    "catalog_payload",
                    return_value={
                        "items": [
                            {"field": "feature_a", "label": "Feature A", "ml_role": "eligible"},
                            {"field": "feature_b", "label": "Feature B", "ml_role": "eligible"},
                        ]
                    },
                ),
            ):
                resolver_cls.return_value.resolve.return_value = source
                feature_export._run_export_job(request_payload)

            root = tmp_path / "exports" / export_id
            x_path = root / "X_genome.csv"
            metadata_path = root / "metadata.csv"
            dictionary_path = root / "feature_dictionary.csv"
            zip_path = root / f"{export_id}.zip"

            self.assertTrue(x_path.exists())
            self.assertTrue(metadata_path.exists())
            self.assertTrue(dictionary_path.exists())
            self.assertFalse((root / "X_genome.csv.gz").exists())
            self.assertFalse((root / "feature_dictionary.tsv").exists())
            self.assertFalse((root / "metadata.tsv").exists())
            self.assertNotEqual(x_path.read_bytes()[:2], b"\x1f\x8b")

            with x_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], ["species_id", "feature_a", "feature_b"])
            self.assertEqual(rows[1], ["species_a", "1.2", "3.4"])

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["tabular_format"], "plain_csv")
            self.assertEqual(manifest["primary_feature_file"], "X_genome.csv")
            self.assertEqual(manifest["metadata_file"], "metadata.csv")
            self.assertEqual(manifest["feature_dictionary_file"], "feature_dictionary.csv")

            with ZipFile(zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn("X_genome.csv", names)
            self.assertIn("metadata.csv", names)
            self.assertIn("feature_dictionary.csv", names)
            self.assertNotIn("X_genome.csv.gz", names)
            self.assertNotIn("feature_dictionary.tsv", names)
            self.assertNotIn("metadata.tsv", names)
