from django.db import models


class DataRelease(models.Model):
    release_id = models.CharField(max_length=128, unique=True)
    label = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    source_root = models.CharField(max_length=1024, blank=True, default='')
    pipeline_root = models.CharField(max_length=1024, blank=True, default='')
    platform_registry_path = models.CharField(max_length=1024, blank=True, default='')
    database_engine = models.CharField(max_length=64, default='postgresql')
    scope_kind = models.CharField(max_length=64, default='global')
    status = models.CharField(max_length=32, default='published')
    version = models.CharField(max_length=64, blank=True, default='')
    schema_version = models.CharField(max_length=64, blank=True, default='')
    pipeline_version = models.CharField(max_length=128, blank=True, default='')
    git_commit = models.CharField(max_length=64, blank=True, default='')
    image_digest = models.CharField(max_length=255, blank=True, default='')
    published_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey('self', related_name='superseded_by', null=True, blank=True, on_delete=models.SET_NULL)
    manifest_sha256 = models.CharField(max_length=64, blank=True, default='')
    is_immutable = models.BooleanField(default=False)
    species_count = models.PositiveIntegerField(default=0)
    dataset_count = models.PositiveIntegerField(default=0)
    entity_row_count = models.PositiveBigIntegerField(default=0)
    artifact_count = models.PositiveIntegerField(default=0)
    feature_file_count = models.PositiveIntegerField(default=0)
    metadata_json = models.JSONField(default=dict, blank=True)
    manifest_json = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['release_id'], name='stoichdb_da_release_c0da1d_idx'),
            models.Index(fields=['is_active'], name='stoichdb_da_is_acti_4b1107_idx'),
            models.Index(fields=['scope_kind'], name='stoichdb_da_scope_k_9f85d2_idx'),
            models.Index(fields=['status'], name='stoichdb_da_status_3815b9_idx'),
            models.Index(fields=['scope_kind', 'status'], name='stoichdb_da_scope_s_eb4377_idx'),
        ]

    def __str__(self):
        return self.label or self.release_id


class Species(models.Model):
    species_id = models.CharField(max_length=128, unique=True)
    display_name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=128, blank=True, default='')
    source_species_id = models.CharField(max_length=255, blank=True, default='')
    taxonomy_id = models.CharField(max_length=64, blank=True, default='')
    domain = models.CharField(max_length=128, blank=True, default='')
    kingdom = models.CharField(max_length=128, blank=True, default='')
    phylum = models.CharField(max_length=128, blank=True, default='')
    clade = models.CharField(max_length=255, blank=True, default='')
    habitat = models.CharField(max_length=255, blank=True, default='')
    source_database = models.CharField(max_length=128, blank=True, default='')
    assembly_version = models.CharField(max_length=128, blank=True, default='')
    genome_size_mb = models.FloatField(default=0.0)
    has_genome = models.BooleanField(default=False)
    has_transcriptome = models.BooleanField(default=False)
    has_proteome = models.BooleanField(default=False)
    fingerprint = models.JSONField(default=dict, blank=True)
    cross_omics_payload = models.JSONField(default=dict, blank=True)
    searchable_text = models.TextField(blank=True, default='')
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_name', 'species_id']
        indexes = [
            models.Index(fields=['species_id']),
            models.Index(fields=['display_name']),
            models.Index(fields=['domain']),
            models.Index(fields=['clade']),
        ]

    def __str__(self):
        return self.display_name


class OmicsDataset(models.Model):
    class OmicsType(models.TextChoices):
        GENOME = 'genome', 'Genome'
        TRANSCRIPTOME = 'transcriptome', 'Transcriptome'
        PROTEOME = 'proteome', 'Proteome'

    dataset_id = models.CharField(max_length=160, unique=True)
    species = models.ForeignKey(Species, related_name='datasets', on_delete=models.CASCADE)
    omics_type = models.CharField(max_length=32, choices=OmicsType.choices)
    schema_version = models.CharField(max_length=64, default='auto_v1')
    row_count_core = models.PositiveIntegerField(default=0)
    row_count_full = models.PositiveIntegerField(default=0)
    core_csv_path = models.CharField(max_length=1024, blank=True, default='')
    full_csv_path = models.CharField(max_length=1024, blank=True, default='')
    status = models.CharField(max_length=64, default='ready')
    browse_meta = models.JSONField(default=dict, blank=True)
    summary_payload = models.JSONField(default=dict, blank=True)
    analysis_payload = models.JSONField(default=dict, blank=True)
    searchable_text = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('species', 'omics_type')
        ordering = ['species__display_name', 'omics_type']
        indexes = [models.Index(fields=['omics_type']), models.Index(fields=['dataset_id'])]

    def __str__(self):
        return f'{self.species.species_id}:{self.omics_type}'


class FeatureFile(models.Model):
    file_id = models.CharField(max_length=200, unique=True)
    dataset = models.ForeignKey(OmicsDataset, related_name='feature_files', on_delete=models.CASCADE)
    file_type = models.CharField(max_length=64)
    path = models.CharField(max_length=1024)
    size_bytes = models.BigIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=['file_type'])]


class AnalysisArtifact(models.Model):
    artifact_id = models.CharField(max_length=200, unique=True)
    species = models.ForeignKey(Species, related_name='artifacts', on_delete=models.CASCADE)
    dataset = models.ForeignKey(OmicsDataset, related_name='artifacts', null=True, blank=True, on_delete=models.CASCADE)
    omics_type = models.CharField(max_length=32, blank=True, default='')
    artifact_type = models.CharField(max_length=64)
    path = models.CharField(max_length=1024, blank=True, default='')
    payload_json = models.JSONField(default=dict, blank=True)
    version = models.CharField(max_length=64, default='v1')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['species', 'artifact_type']),
            models.Index(fields=['omics_type', 'artifact_type']),
        ]


class StorageObject(models.Model):
    logical_key = models.CharField(max_length=512, unique=True)
    backend = models.CharField(max_length=64, default='local_fs')
    root_alias = models.CharField(max_length=128, blank=True, default='STOICH_DATA_ROOT')
    relative_path = models.CharField(max_length=2048, blank=True, default='')
    object_uri = models.CharField(max_length=2048, blank=True, default='')
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default='')
    media_type = models.CharField(max_length=128, blank=True, default='')
    compression = models.CharField(max_length=64, blank=True, default='')
    schema_version = models.CharField(max_length=64, blank=True, default='')
    status = models.CharField(max_length=32, default='registered')
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['logical_key']
        indexes = [
            models.Index(fields=['backend', 'root_alias']),
            models.Index(fields=['status']),
            models.Index(fields=['sha256']),
            models.Index(fields=['schema_version']),
        ]

    def __str__(self):
        return self.logical_key


class ReleaseSpecies(models.Model):
    release = models.ForeignKey(DataRelease, related_name='species_memberships', on_delete=models.CASCADE)
    species = models.ForeignKey(Species, related_name='release_memberships', null=True, blank=True, on_delete=models.SET_NULL)
    species_id_text = models.CharField(max_length=128)
    inclusion_status = models.CharField(max_length=64, default='included')
    reason_code = models.CharField(max_length=128, blank=True, default='')
    qc_status = models.CharField(max_length=64, default='pending')
    is_model_organism = models.BooleanField(default=False)
    model_group_latin = models.CharField(max_length=255, blank=True, default='')
    expected_model_group = models.CharField(max_length=64, blank=True, default='')
    source_division = models.CharField(max_length=64, blank=True, default='')
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('release', 'species_id_text')
        ordering = ['release__release_id', 'species_id_text']
        indexes = [
            models.Index(fields=['species_id_text']),
            models.Index(fields=['inclusion_status']),
            models.Index(fields=['qc_status']),
            models.Index(fields=['is_model_organism']),
            models.Index(fields=['source_division']),
        ]

    def __str__(self):
        return f'{self.release.release_id}:{self.species_id_text}'


class ReleaseDataset(models.Model):
    release = models.ForeignKey(DataRelease, related_name='dataset_memberships', on_delete=models.CASCADE)
    species = models.ForeignKey(Species, related_name='release_dataset_memberships', null=True, blank=True, on_delete=models.SET_NULL)
    dataset = models.ForeignKey(OmicsDataset, related_name='release_memberships', null=True, blank=True, on_delete=models.SET_NULL)
    species_id_text = models.CharField(max_length=128)
    dataset_id_text = models.CharField(max_length=160)
    omics_type = models.CharField(max_length=32)
    membership_status = models.CharField(max_length=64, default='included')
    reason_code = models.CharField(max_length=128, blank=True, default='')
    row_count_core = models.PositiveIntegerField(default=0)
    row_count_full = models.PositiveIntegerField(default=0)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('release', 'species_id_text', 'omics_type')
        ordering = ['release__release_id', 'species_id_text', 'omics_type']
        indexes = [
            models.Index(fields=['dataset_id_text']),
            models.Index(fields=['species_id_text', 'omics_type']),
            models.Index(fields=['membership_status']),
        ]

    def __str__(self):
        return f'{self.release.release_id}:{self.dataset_id_text}'


class SchemaRegistry(models.Model):
    schema_id = models.CharField(max_length=160, unique=True)
    omics_type = models.CharField(max_length=32, blank=True, default='')
    product_type = models.CharField(max_length=64, blank=True, default='')
    version = models.CharField(max_length=64, default='v1')
    status = models.CharField(max_length=32, default='draft')
    columns_json = models.JSONField(default=list, blank=True)
    rules_json = models.JSONField(default=dict, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['schema_id']
        indexes = [
            models.Index(fields=['omics_type', 'product_type']),
            models.Index(fields=['status']),
            models.Index(fields=['version']),
        ]

    def __str__(self):
        return self.schema_id


class ProvenanceRun(models.Model):
    run_id = models.CharField(max_length=160, unique=True)
    release = models.ForeignKey(DataRelease, related_name='provenance_runs', null=True, blank=True, on_delete=models.SET_NULL)
    pipeline_name = models.CharField(max_length=160)
    git_commit = models.CharField(max_length=64, blank=True, default='')
    image_digest = models.CharField(max_length=255, blank=True, default='')
    software_versions = models.JSONField(default=dict, blank=True)
    parameters_json = models.JSONField(default=dict, blank=True)
    random_seed = models.CharField(max_length=64, blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, default='registered')
    log_object = models.ForeignKey(StorageObject, related_name='provenance_logs', null=True, blank=True, on_delete=models.SET_NULL)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', 'run_id']
        indexes = [
            models.Index(fields=['pipeline_name']),
            models.Index(fields=['status']),
            models.Index(fields=['release', 'pipeline_name']),
        ]

    def __str__(self):
        return self.run_id


class FileQCResult(models.Model):
    release = models.ForeignKey(DataRelease, related_name='file_qc_results', null=True, blank=True, on_delete=models.SET_NULL)
    storage_object = models.ForeignKey(StorageObject, related_name='qc_results', null=True, blank=True, on_delete=models.SET_NULL)
    check_name = models.CharField(max_length=128)
    status = models.CharField(max_length=32, default='pending')
    reason_code = models.CharField(max_length=128, blank=True, default='')
    metrics_json = models.JSONField(default=dict, blank=True)
    threshold_json = models.JSONField(default=dict, blank=True)
    details_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', 'check_name']
        indexes = [
            models.Index(fields=['check_name']),
            models.Index(fields=['status']),
            models.Index(fields=['reason_code']),
        ]

    def __str__(self):
        target = self.storage_object.logical_key if self.storage_object_id else 'unbound'
        return f'{self.check_name}:{target}'


class ReleaseQCResult(models.Model):
    release = models.ForeignKey(DataRelease, related_name='release_qc_results', on_delete=models.CASCADE)
    gate = models.CharField(max_length=64)
    status = models.CharField(max_length=32, default='pending')
    report_object = models.ForeignKey(StorageObject, related_name='release_qc_reports', null=True, blank=True, on_delete=models.SET_NULL)
    summary_json = models.JSONField(default=dict, blank=True)
    approved_by = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('release', 'gate')
        ordering = ['release__release_id', 'gate']
        indexes = [
            models.Index(fields=['gate']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.release.release_id}:{self.gate}'


class GeneIndex(models.Model):
    species = models.ForeignKey(Species, related_name='gene_index', on_delete=models.CASCADE)
    gene_id = models.CharField(max_length=255)
    gene_name = models.CharField(max_length=255, blank=True, default='')
    locus_tag = models.CharField(max_length=255, blank=True, default='')
    biotype = models.CharField(max_length=128, blank=True, default='')
    seqid = models.CharField(max_length=128, blank=True, default='')
    start_1 = models.IntegerField(null=True, blank=True)
    end_1 = models.IntegerField(null=True, blank=True)
    strand = models.CharField(max_length=32, blank=True, default='')

    class Meta:
        unique_together = ('species', 'gene_id')
        indexes = [models.Index(fields=['gene_id']), models.Index(fields=['gene_name'])]


class TranscriptIndex(models.Model):
    species = models.ForeignKey(Species, related_name='transcript_index', on_delete=models.CASCADE)
    transcript_id = models.CharField(max_length=255)
    gene_id = models.CharField(max_length=255, blank=True, default='')
    gene_symbol = models.CharField(max_length=255, blank=True, default='')
    transcript_biotype = models.CharField(max_length=128, blank=True, default='')
    seq_region = models.CharField(max_length=128, blank=True, default='')
    start = models.IntegerField(null=True, blank=True)
    end = models.IntegerField(null=True, blank=True)
    strand = models.CharField(max_length=32, blank=True, default='')

    class Meta:
        unique_together = ('species', 'transcript_id')
        indexes = [models.Index(fields=['transcript_id']), models.Index(fields=['gene_id']), models.Index(fields=['gene_symbol'])]


class ProteinIndex(models.Model):
    species = models.ForeignKey(Species, related_name='protein_index', on_delete=models.CASCADE)
    protein_id = models.CharField(max_length=255)
    ensembl_gene_id = models.CharField(max_length=255, blank=True, default='')
    gene_id = models.CharField(max_length=255, blank=True, default='')
    gene_symbol = models.CharField(max_length=255, blank=True, default='')
    description = models.TextField(blank=True, default='')
    length_aa = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ('species', 'protein_id')
        indexes = [models.Index(fields=['protein_id']), models.Index(fields=['ensembl_gene_id']), models.Index(fields=['gene_symbol'])]


class EntityRecord(models.Model):
    dataset = models.ForeignKey(OmicsDataset, related_name='entity_rows', on_delete=models.CASCADE)
    species = models.ForeignKey(Species, related_name='entity_rows', on_delete=models.CASCADE)
    omics_type = models.CharField(max_length=32)
    entity_id = models.CharField(max_length=255)
    canonical_gene_id = models.CharField(max_length=255, blank=True, default='')
    secondary_id = models.CharField(max_length=255, blank=True, default='')
    gene_name = models.CharField(max_length=255, blank=True, default='')
    description = models.TextField(blank=True, default='')
    strategy_cluster = models.CharField(max_length=128, blank=True, default='')
    seqid = models.CharField(max_length=128, blank=True, default='')
    start_pos = models.IntegerField(null=True, blank=True)
    end_pos = models.IntegerField(null=True, blank=True)
    payload_json = models.JSONField(default=dict, blank=True)
    searchable_text = models.TextField(blank=True, default='')
    numeric_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('dataset', 'entity_id')
        ordering = ['entity_id']
        indexes = [
            models.Index(fields=['species', 'omics_type']),
            models.Index(fields=['dataset', 'strategy_cluster']),
            models.Index(fields=['entity_id']),
            models.Index(fields=['canonical_gene_id']),
            models.Index(fields=['gene_name']),
        ]

    def __str__(self):
        return f'{self.dataset.dataset_id}:{self.entity_id}'


class FunctionalAnnotationRelease(models.Model):
    release_id = models.CharField(max_length=128, unique=True)
    label = models.CharField(max_length=255)
    source_dir = models.CharField(max_length=1024, blank=True, default='')
    go_source = models.CharField(max_length=255, blank=True, default='UniProtKB/GO')
    kegg_source = models.CharField(max_length=255, blank=True, default='KEGG REST from UniProtKB cross references')
    species_total = models.PositiveIntegerField(default=0)
    go_species_count = models.PositiveIntegerField(default=0)
    kegg_species_count = models.PositiveIntegerField(default=0)
    go_annotation_count = models.PositiveBigIntegerField(default=0)
    kegg_gene_count = models.PositiveBigIntegerField(default=0)
    kegg_link_count = models.PositiveBigIntegerField(default=0)
    manifest_json = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['release_id']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.label or self.release_id


class SpeciesFunctionalAnnotationStatus(models.Model):
    species = models.OneToOneField(Species, related_name='functional_annotation_status', null=True, blank=True, on_delete=models.SET_NULL)
    release = models.ForeignKey(FunctionalAnnotationRelease, related_name='species_statuses', null=True, blank=True, on_delete=models.SET_NULL)
    species_id_text = models.CharField(max_length=128)
    tax_id = models.CharField(max_length=64, blank=True, default='')
    tax_name = models.CharField(max_length=255, blank=True, default='')
    assembly_accession = models.CharField(max_length=128, blank=True, default='')
    ensembl_release = models.CharField(max_length=64, blank=True, default='')
    mapped_uniprot_rows = models.PositiveIntegerField(default=0)
    unique_uniprot_accessions = models.PositiveIntegerField(default=0)
    go_rows = models.PositiveIntegerField(default=0)
    uniprot_kegg_xref_rows = models.PositiveIntegerField(default=0)
    kegg_code = models.CharField(max_length=32, blank=True, default='')
    kegg_t_number = models.CharField(max_length=32, blank=True, default='')
    kegg_name = models.CharField(max_length=255, blank=True, default='')
    kegg_match_status = models.CharField(max_length=64, blank=True, default='not_matched')
    kegg_gene_rows = models.PositiveIntegerField(default=0)
    kegg_ko_rows = models.PositiveIntegerField(default=0)
    kegg_pathway_rows = models.PositiveIntegerField(default=0)
    kegg_module_rows = models.PositiveIntegerField(default=0)
    kegg_joined_rows = models.PositiveIntegerField(default=0)
    status_note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['species_id_text']
        indexes = [
            models.Index(fields=['species_id_text']),
            models.Index(fields=['kegg_match_status']),
            models.Index(fields=['go_rows']),
            models.Index(fields=['kegg_joined_rows']),
        ]

    def __str__(self):
        return self.species_id_text


class GOTerm(models.Model):
    go_id = models.CharField(max_length=32, unique=True)
    go_name = models.TextField(blank=True, default='')
    namespace = models.CharField(max_length=64, blank=True, default='')
    definition = models.TextField(blank=True, default='')
    is_obsolete = models.BooleanField(default=False)

    class Meta:
        ordering = ['go_id']
        indexes = [
            models.Index(fields=['go_id']),
            models.Index(fields=['namespace']),
            models.Index(fields=['is_obsolete']),
        ]

    def __str__(self):
        return self.go_id


class GOAnnotation(models.Model):
    species = models.ForeignKey(Species, related_name='go_annotations', null=True, blank=True, on_delete=models.SET_NULL)
    release = models.ForeignKey(FunctionalAnnotationRelease, related_name='go_annotations', null=True, blank=True, on_delete=models.SET_NULL)
    species_id_text = models.CharField(max_length=128)
    tax_id = models.CharField(max_length=64, blank=True, default='')
    tax_name = models.CharField(max_length=255, blank=True, default='')
    gene_id = models.CharField(max_length=255, blank=True, default='')
    transcript_id = models.CharField(max_length=255, blank=True, default='')
    protein_id = models.CharField(max_length=255, blank=True, default='')
    source_protein_id = models.CharField(max_length=255, blank=True, default='')
    mapping_confidence = models.CharField(max_length=32, blank=True, default='')
    mapping_evidence = models.TextField(blank=True, default='')
    uniprot_accession = models.CharField(max_length=64, blank=True, default='')
    go_term = models.ForeignKey(GOTerm, related_name='annotations', null=True, blank=True, on_delete=models.SET_NULL)
    go_id = models.CharField(max_length=32)
    go_name = models.TextField(blank=True, default='')
    go_namespace = models.CharField(max_length=64, blank=True, default='')
    go_is_obsolete = models.BooleanField(default=False)
    source = models.CharField(max_length=128, blank=True, default='')
    annotation_status = models.CharField(max_length=64, blank=True, default='standard_database')

    class Meta:
        indexes = [
            models.Index(fields=['species_id_text', 'go_id']),
            models.Index(fields=['species_id_text', 'gene_id']),
            models.Index(fields=['species_id_text', 'protein_id']),
            models.Index(fields=['uniprot_accession']),
            models.Index(fields=['go_namespace']),
        ]


class KEGGGeneAnnotation(models.Model):
    species = models.ForeignKey(Species, related_name='kegg_gene_annotations', null=True, blank=True, on_delete=models.SET_NULL)
    release = models.ForeignKey(FunctionalAnnotationRelease, related_name='kegg_gene_annotations', null=True, blank=True, on_delete=models.SET_NULL)
    species_id_text = models.CharField(max_length=128)
    tax_id = models.CharField(max_length=64, blank=True, default='')
    tax_name = models.CharField(max_length=255, blank=True, default='')
    gene_id = models.CharField(max_length=255, blank=True, default='')
    transcript_id = models.CharField(max_length=255, blank=True, default='')
    protein_id = models.CharField(max_length=255, blank=True, default='')
    source_protein_id = models.CharField(max_length=255, blank=True, default='')
    mapping_confidence = models.CharField(max_length=32, blank=True, default='')
    mapping_evidence = models.TextField(blank=True, default='')
    uniprot_accession = models.CharField(max_length=64, blank=True, default='')
    kegg_gene_id = models.CharField(max_length=128, blank=True, default='')
    kegg_org_code = models.CharField(max_length=32, blank=True, default='')
    kegg_gene_description = models.TextField(blank=True, default='')
    ko_ids = models.TextField(blank=True, default='')
    ko_names = models.TextField(blank=True, default='')
    pathway_ids = models.TextField(blank=True, default='')
    pathway_names = models.TextField(blank=True, default='')
    module_ids = models.TextField(blank=True, default='')
    module_names = models.TextField(blank=True, default='')
    source = models.CharField(max_length=128, blank=True, default='')
    annotation_status = models.CharField(max_length=64, blank=True, default='standard_database')

    class Meta:
        indexes = [
            models.Index(fields=['species_id_text', 'gene_id']),
            models.Index(fields=['species_id_text', 'protein_id']),
            models.Index(fields=['uniprot_accession']),
            models.Index(fields=['kegg_gene_id']),
            models.Index(fields=['kegg_org_code']),
        ]


class KEGGAnnotationLink(models.Model):
    species = models.ForeignKey(Species, related_name='kegg_annotation_links', null=True, blank=True, on_delete=models.SET_NULL)
    release = models.ForeignKey(FunctionalAnnotationRelease, related_name='kegg_annotation_links', null=True, blank=True, on_delete=models.SET_NULL)
    species_id_text = models.CharField(max_length=128)
    tax_id = models.CharField(max_length=64, blank=True, default='')
    tax_name = models.CharField(max_length=255, blank=True, default='')
    gene_id = models.CharField(max_length=255, blank=True, default='')
    transcript_id = models.CharField(max_length=255, blank=True, default='')
    protein_id = models.CharField(max_length=255, blank=True, default='')
    uniprot_accession = models.CharField(max_length=64, blank=True, default='')
    kegg_gene_id = models.CharField(max_length=128, blank=True, default='')
    kegg_org_code = models.CharField(max_length=32, blank=True, default='')
    kegg_gene_description = models.TextField(blank=True, default='')
    annotation_type = models.CharField(max_length=32)
    annotation_id = models.CharField(max_length=128)
    annotation_name = models.TextField(blank=True, default='')
    source = models.CharField(max_length=128, blank=True, default='')
    annotation_status = models.CharField(max_length=64, blank=True, default='standard_database')

    class Meta:
        indexes = [
            models.Index(fields=['species_id_text', 'annotation_type']),
            models.Index(fields=['species_id_text', 'annotation_id']),
            models.Index(fields=['species_id_text', 'gene_id']),
            models.Index(fields=['species_id_text', 'protein_id']),
        ]


class EntityFunctionalProfile(models.Model):
    species = models.ForeignKey(Species, related_name='entity_functional_profiles', null=True, blank=True, on_delete=models.SET_NULL)
    release = models.ForeignKey(FunctionalAnnotationRelease, related_name='entity_functional_profiles', null=True, blank=True, on_delete=models.SET_NULL)
    species_id_text = models.CharField(max_length=128)
    entity_key = models.CharField(max_length=255)
    gene_id = models.CharField(max_length=255, blank=True, default='')
    transcript_id = models.CharField(max_length=255, blank=True, default='')
    protein_id = models.CharField(max_length=255, blank=True, default='')
    uniprot_accession = models.CharField(max_length=64, blank=True, default='')
    go_terms = models.JSONField(default=list, blank=True)
    kegg_terms = models.JSONField(default=list, blank=True)
    profile_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('species_id_text', 'entity_key')
        indexes = [
            models.Index(fields=['species_id_text', 'entity_key']),
            models.Index(fields=['gene_id']),
            models.Index(fields=['protein_id']),
        ]


class SpeciesFunctionalProfile(models.Model):
    species = models.OneToOneField(Species, related_name='functional_profile', null=True, blank=True, on_delete=models.SET_NULL)
    release = models.ForeignKey(FunctionalAnnotationRelease, related_name='species_functional_profiles', null=True, blank=True, on_delete=models.SET_NULL)
    species_id_text = models.CharField(max_length=128, unique=True)
    summary_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['species_id_text'])]


class FunctionalEnrichmentResult(models.Model):
    species = models.ForeignKey(Species, related_name='functional_enrichment_results', null=True, blank=True, on_delete=models.SET_NULL)
    release = models.ForeignKey(FunctionalAnnotationRelease, related_name='enrichment_results', null=True, blank=True, on_delete=models.SET_NULL)
    analysis_id = models.CharField(max_length=160, unique=True)
    species_id_text = models.CharField(max_length=128)
    annotation_type = models.CharField(max_length=32)
    query_hash = models.CharField(max_length=64)
    query_entities = models.JSONField(default=list, blank=True)
    universe_size = models.PositiveIntegerField(default=0)
    query_size = models.PositiveIntegerField(default=0)
    result_json = models.JSONField(default=dict, blank=True)
    method_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['analysis_id']),
            models.Index(fields=['species_id_text', 'annotation_type']),
            models.Index(fields=['query_hash']),
        ]


class FunctionalAnnotationIngestionLog(models.Model):
    release = models.ForeignKey(FunctionalAnnotationRelease, related_name='ingestion_logs', null=True, blank=True, on_delete=models.SET_NULL)
    source_dir = models.CharField(max_length=1024, blank=True, default='')
    status = models.CharField(max_length=32, default='started')
    rows_json = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at', '-id']
        indexes = [models.Index(fields=['status'])]


class PhylogenyRelease(models.Model):
    release_id = models.CharField(max_length=128, unique=True)
    label = models.CharField(max_length=255)
    scope = models.CharField(max_length=64, default='protists')
    tree_kind = models.CharField(max_length=128, default='taxonomy_reference_topology')
    source = models.CharField(max_length=255, blank=True, default='')
    source_version = models.CharField(max_length=255, blank=True, default='')
    method = models.TextField(blank=True, default='')
    rooted = models.BooleanField(default=True)
    branch_length_unit = models.CharField(max_length=64, blank=True, default='none')
    tip_count = models.PositiveIntegerField(default=0)
    analysis_eligible = models.BooleanField(default=False)
    topology_eligible = models.BooleanField(default=True)
    tree_path = models.CharField(max_length=1024, blank=True, default='')
    tree_sha256 = models.CharField(max_length=64, blank=True, default='')
    tip_map_path = models.CharField(max_length=1024, blank=True, default='')
    tip_map_sha256 = models.CharField(max_length=64, blank=True, default='')
    metadata_json = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['release_id'], name='stoichdb_ph_release_69d6ca_idx'),
            models.Index(fields=['scope', 'is_active'], name='stoichdb_ph_scope_7c0d1d_idx'),
            models.Index(fields=['tree_kind'], name='stoichdb_ph_tree_ki_e37b18_idx'),
        ]


class PhylogenyTipMap(models.Model):
    release = models.ForeignKey(PhylogenyRelease, related_name='tip_maps', on_delete=models.CASCADE)
    species = models.ForeignKey(Species, related_name='phylogeny_tip_maps', null=True, blank=True, on_delete=models.SET_NULL)
    species_id_text = models.CharField(max_length=128)
    tip_label = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True, default='')
    tax_id = models.CharField(max_length=64, blank=True, default='')
    full_lineage = models.TextField(blank=True, default='')
    rank_json = models.JSONField(default=dict, blank=True)
    mapping_status = models.CharField(max_length=64, default='mapped')
    topology_eligible = models.BooleanField(default=True)
    pgls_eligible = models.BooleanField(default=False)
    pgls_blocker = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        unique_together = ('release', 'species_id_text')
        indexes = [
            models.Index(fields=['species_id_text'], name='stoichdb_ph_species_4b808e_idx'),
            models.Index(fields=['tip_label'], name='stoichdb_ph_tip_lab_9fd326_idx'),
            models.Index(fields=['tax_id'], name='stoichdb_ph_tax_id_0f5fbb_idx'),
            models.Index(fields=['mapping_status'], name='stoichdb_ph_mapping_396bb7_idx'),
        ]


class PhylogenyQCMetric(models.Model):
    release = models.ForeignKey(PhylogenyRelease, related_name='qc_metrics', on_delete=models.CASCADE)
    metric = models.CharField(max_length=128)
    value = models.CharField(max_length=128, blank=True, default='')
    status = models.CharField(max_length=32, default='pass')
    detail = models.TextField(blank=True, default='')

    class Meta:
        unique_together = ('release', 'metric')
        indexes = [
            models.Index(fields=['metric'], name='stoichdb_ph_metric_53fd38_idx'),
            models.Index(fields=['status'], name='stoichdb_ph_status_73e11b_idx'),
        ]


class PhylogeneticSignalResult(models.Model):
    release = models.ForeignKey(PhylogenyRelease, related_name='signal_results', null=True, blank=True, on_delete=models.SET_NULL)
    analysis_id = models.CharField(max_length=160, unique=True)
    feature = models.CharField(max_length=128)
    n_species = models.PositiveIntegerField(default=0)
    lambda_value = models.FloatField(null=True, blank=True)
    p_value = models.FloatField(null=True, blank=True)
    q_value = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=64, default='pending')
    blocker = models.CharField(max_length=255, blank=True, default='')
    result_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['feature'], name='stoichdb_ph_feature_986e0a_idx'),
            models.Index(fields=['status'], name='stoichdb_ph_status_0922f0_idx'),
            models.Index(fields=['analysis_id'], name='stoichdb_ph_analysi_6e0cde_idx'),
        ]


class ComparativeAnalysisRun(models.Model):
    release = models.ForeignKey(PhylogenyRelease, related_name='comparative_runs', null=True, blank=True, on_delete=models.SET_NULL)
    analysis_id = models.CharField(max_length=160, unique=True)
    analysis_type = models.CharField(max_length=64, default='pgls')
    formula = models.CharField(max_length=255, blank=True, default='')
    n_species = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=64, default='pending')
    blocker = models.CharField(max_length=255, blank=True, default='')
    result_json = models.JSONField(default=dict, blank=True)
    method_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['analysis_id'], name='stoichdb_co_analysi_ddaf02_idx'),
            models.Index(fields=['analysis_type'], name='stoichdb_co_analysi_647134_idx'),
            models.Index(fields=['status'], name='stoichdb_co_status_ea6fd5_idx'),
        ]


# Dedicated Core comparison tables; legacy models and payloads are unchanged.
from .compare_core.models import CompareCoreProfile, CompareRun


class CoreProjectionRecipe(models.Model):
    """Versioned storage projection. Scientific feature definitions stay unchanged."""
    recipe_id = models.CharField(max_length=64, unique=True)
    omics_type = models.CharField(max_length=32)
    version = models.CharField(max_length=64, default='extractor-projection-v1')
    schema_hash = models.CharField(max_length=64)
    columns_json = models.JSONField(default=list)
    fill_noncoding = models.CharField(max_length=16, default='zero')
    serialization_json = models.JSONField(default=dict)
    extractor_sha256 = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)


class FeatureSourceBinding(models.Model):
    """An explicitly verified logical Core alias backed by an immutable Full asset."""
    binding_id = models.CharField(max_length=64, unique=True)
    dataset = models.ForeignKey(OmicsDataset, on_delete=models.PROTECT, related_name='source_bindings', null=True, blank=True)
    recipe = models.ForeignKey(CoreProjectionRecipe, on_delete=models.PROTECT)
    release_context = models.CharField(max_length=200, blank=True, default='')
    legacy_source_key = models.CharField(max_length=64)
    legacy_path = models.CharField(max_length=2048)
    logical_scope = models.CharField(max_length=16, default='core')
    representation = models.CharField(max_length=32, default='csv')
    full_path = models.CharField(max_length=2048)
    full_sha256 = models.CharField(max_length=64)
    core_sha256 = models.CharField(max_length=64)
    virtual_csv_sha256 = models.CharField(max_length=64)
    logical_cell_hash = models.CharField(max_length=64)
    row_count = models.PositiveBigIntegerField(default=0)
    virtual_size = models.PositiveBigIntegerField(default=0)
    legacy_stat_json = models.JSONField(default=dict)
    full_stat_json = models.JSONField(default=dict)
    receipt_json = models.JSONField(default=dict)
    status = models.CharField(max_length=32, default='shadow')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['dataset', 'release_context', 'legacy_source_key'], name='unique_corefull_source_context'),
            models.UniqueConstraint(fields=['release_context','legacy_source_key'],condition=models.Q(dataset__isnull=True),name='unique_corefull_library_alias'),
        ]
        indexes = [models.Index(fields=['legacy_source_key', 'status'], name='corefull_alias_status')]
