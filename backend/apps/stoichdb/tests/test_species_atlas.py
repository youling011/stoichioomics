import csv
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from backend.apps.stoichdb import services
from backend.apps.stoichdb.management.commands.backfill_species_genome_size import _compute_genome_size_from_csv
from backend.apps.stoichdb.models import OmicsDataset, Species


class SpeciesAtlasSummaryTests(TestCase):
    def setUp(self):
        self.bacteria = Species.objects.create(
            species_id="bacteria_a",
            display_name="Bacteria A",
            domain="Bacteria",
            genome_size_mb=4.2,
            has_genome=True,
            has_transcriptome=True,
            has_proteome=True,
        )
        self.fungus = Species.objects.create(
            species_id="fungus_b",
            display_name="Fungus B",
            domain="Fungi",
            genome_size_mb=36.0,
            has_genome=True,
            has_transcriptome=False,
            has_proteome=False,
        )
        self.unknown = Species.objects.create(
            species_id="unknown_c",
            display_name="Unknown C",
            domain="Unknown",
            genome_size_mb=0,
            has_genome=False,
            has_transcriptome=False,
            has_proteome=False,
        )
        for omics in ("genome", "transcriptome", "proteome"):
            OmicsDataset.objects.create(
                dataset_id=f"bacteria_a:{omics}",
                species=self.bacteria,
                omics_type=omics,
                row_count_core=10,
                core_csv_path=f"/tmp/bacteria_a.{omics}.core.csv",
                status="ready",
            )
        OmicsDataset.objects.create(
            dataset_id="fungus_b:genome",
            species=self.fungus,
            omics_type="genome",
            row_count_core=5,
            core_csv_path="/tmp/fungus_b.genome.core.csv",
            status="ready",
        )
        services.db_mode.cache_clear()
        services.species_atlas_summary.cache_clear()

    def tearDown(self):
        services.db_mode.cache_clear()
        services.species_atlas_summary.cache_clear()

    def test_availability_sums_to_total_and_uses_full_context(self):
        payload = services.species_atlas_summary()
        availability = payload["omics_availability"]
        self.assertEqual(payload["meta"]["species_total"], 3)
        self.assertEqual(sum(availability.values()), 3)
        self.assertEqual(availability["all_3"], 1)
        self.assertEqual(availability["one_omics"], 1)
        self.assertEqual(availability["no_omics"], 1)

    def test_has_all_omics_query_param_does_not_self_condition_atlas(self):
        response = self.client.get("/api/stoichdb/species/atlas-summary/", {"has_all_omics": "1"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["meta"]["species_total"], 3)
        self.assertEqual(payload["domain_omics_coverage"]["all_domains"]["all_three"]["available"], 1)

    def test_unknown_domain_is_appended_when_present(self):
        payload = services.species_atlas_summary()
        self.assertEqual(payload["meta"]["domain_order"][-1], "Unclassified")

    def test_genome_size_zero_is_excluded_from_log_distribution(self):
        payload = services.species_atlas_summary()
        rows = {row["domain"]: row for row in payload["genome_size_distribution"]}
        self.assertEqual(rows["Unclassified"]["n"], 0)
        self.assertEqual(rows["Unclassified"]["excluded_count"], 1)


class GenomeSizeBackfillTests(SimpleTestCase):
    def test_compute_genome_size_uses_max_end_per_seqid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.genome_features.core.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["gene_id", "seqid", "start_1", "end_1"])
                writer.writerow(["g1", "chr1", 1, 1000])
                writer.writerow(["g2", "chr1", 2000, 3000])
                writer.writerow(["g3", "chr2", 1, 7000])
            result = _compute_genome_size_from_csv(str(path))
        self.assertTrue(result["ok"])
        self.assertEqual(result["seq_count"], 2)
        self.assertAlmostEqual(result["genome_size_mb"], 0.01, places=6)
