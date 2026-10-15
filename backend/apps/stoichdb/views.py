from pathlib import Path

from django.http import FileResponse
from rest_framework.decorators import api_view

from backend.apps.common.responses import ok, err
from . import services
from . import case_studies
from . import function_annotations
from . import id_mapping
from . import phylogeny
from .feature_hub import api as feature_hub_api
from .feature_hub.schemas import FeatureHubError


@api_view(['GET'])
def home_view(request):
    return ok(services.home_payload())


@api_view(['GET'])
def release_view(request):
    return ok(services.release_overview())


@api_view(['GET'])
def analysis_hub_view(request):
    return ok(services.analysis_hub_payload())


@api_view(['GET'])
def case_studies_view(request):
    try:
        return ok(case_studies.case_study_gallery_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def case1_taxonomy_advanced_view(request):
    try:
        return ok(case_studies.build_case1_taxonomy_advanced())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case1_summary_view(request):
    try:
        return ok(case_studies.model8_case1_summary_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case1_matrix_view(request):
    try:
        return ok(case_studies.model8_case1_matrix_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case1_pairwise_view(request):
    try:
        return ok(case_studies.model8_case1_pairwise_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case1_sensitivity_view(request):
    try:
        return ok(case_studies.model8_case1_sensitivity_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case2_summary_view(request):
    try:
        return ok(case_studies.model8_case2_summary_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case2_coupling_view(request):
    try:
        return ok(case_studies.model8_case2_coupling_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case2_null_models_view(request):
    try:
        return ok(case_studies.model8_case2_null_models_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case2_sensitivity_view(request):
    try:
        return ok(case_studies.model8_case2_sensitivity_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case3_summary_view(request):
    try:
        return ok(case_studies.model8_case3_summary_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case3_candidates_view(request):
    try:
        return ok(case_studies.model8_case3_candidates_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case3_reports_view(request):
    try:
        return ok(case_studies.model8_case3_reports_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case3_sensitivity_view(request):
    try:
        return ok(case_studies.model8_case3_sensitivity_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case4_summary_view(request):
    try:
        return ok(case_studies.model8_case4_summary_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case4_gold_view(request):
    try:
        return ok(case_studies.model8_case4_gold_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case4_workflows_view(request):
    try:
        return ok(case_studies.model8_case4_workflows_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case4_validation_view(request):
    try:
        return ok(case_studies.model8_case4_validation_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case4_species_view(request, case_code):
    try:
        return ok(case_studies.model8_case4_species_payload(case_code))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case5_summary_view(request):
    try:
        return ok(case_studies.model8_case5_summary_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case5_phase1_view(request):
    try:
        return ok(case_studies.model8_case5_phase1_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case5_phase2_view(request):
    try:
        return ok(case_studies.model8_case5_phase2_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case5_downstream_view(request):
    try:
        return ok(case_studies.model8_case5_downstream_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_case5_species_view(request, case_code):
    try:
        return ok(case_studies.model8_case5_species_payload(case_code))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def model8_platform_release_view(request):
    try:
        return ok(case_studies.model8_platform_release_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def download_model8_platform_bundle_view(request):
    try:
        path = case_studies.resolve_model8_platform_file('__bundle__')
        return FileResponse(path.open('rb'), as_attachment=True, filename=Path(path).name)
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def download_model8_platform_file_view(request, relative_path: str):
    try:
        path = case_studies.resolve_model8_platform_file(relative_path)
        return FileResponse(path.open('rb'), as_attachment=True, filename=Path(path).name)
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def phylogeny_releases_view(request):
    return ok(phylogeny.releases_payload())


@api_view(['GET'])
def phylogeny_release_view(request, release_id: str):
    payload = phylogeny.release_payload(release_id)
    if not payload.get('available'):
        return err(payload.get('message', 'Unknown phylogeny release.'), status=404)
    return ok(payload)


@api_view(['GET'])
def phylogeny_tree_view(request, release_id: str):
    try:
        return ok(phylogeny.tree_payload(release_id))
    except phylogeny.PhylogenyNotFound as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def phylogeny_validation_view(request, release_id: str):
    try:
        return ok(phylogeny.validation_payload(release_id))
    except phylogeny.PhylogenyNotFound as exc:
        return err(str(exc), status=404)


@api_view(['POST'])
def phylogeny_signal_view(request):
    try:
        return ok(phylogeny.signal_payload(request.data or {}))
    except (phylogeny.PhylogenyNotFound, ValueError) as exc:
        return err(str(exc), status=400)


@api_view(['POST'])
def phylogeny_pgls_view(request):
    try:
        return ok(phylogeny.pgls_payload(request.data or {}))
    except (phylogeny.PhylogenyNotFound, ValueError) as exc:
        return err(str(exc), status=400)


@api_view(['GET'])
def case1_phylogeny_view(request):
    try:
        return ok(phylogeny.case1_phylogeny_payload(release_id=request.GET.get('release_id', '')))
    except phylogeny.PhylogenyNotFound as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def id_mapping_resolve_view(request):
    return ok(id_mapping.resolve_id(
        request.GET.get('query') or request.GET.get('q') or '',
        species_id=request.GET.get('species_id', ''),
        limit=request.GET.get('limit', 25),
    ))


@api_view(['POST'])
def id_mapping_batch_resolve_view(request):
    payload = request.data or {}
    queries = payload.get('queries') or payload.get('ids') or []
    if isinstance(queries, str):
        queries = [item.strip() for item in queries.replace(',', '\n').splitlines() if item.strip()]
    return ok(id_mapping.batch_resolve_ids(
        queries,
        species_id=payload.get('species_id', ''),
        limit_per_query=payload.get('limit_per_query', 10),
    ))


@api_view(['GET'])
def id_mapping_search_view(request):
    return ok(id_mapping.search_mappings(
        query=request.GET.get('query') or request.GET.get('q') or '',
        species_id=request.GET.get('species_id', ''),
        id_type=request.GET.get('id_type', ''),
        mapping_confidence=request.GET.get('mapping_confidence', ''),
        mapping_status=request.GET.get('mapping_status', ''),
        mapping_level=request.GET.get('mapping_level', ''),
        external_status=request.GET.get('external_status', ''),
        conflict_only=str(request.GET.get('conflict_only', '')).lower() in {'1', 'true', 'yes', 'on'},
        limit=request.GET.get('limit', 50),
    ))


@api_view(['GET'])
def id_mapping_manifest_view(request):
    return ok(id_mapping.manifest_payload())


@api_view(['GET'])
def species_id_mapping_summary_view(request, species_id: str):
    try:
        return ok(id_mapping.get_species_mapping_summary(species_id))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def species_id_mapping_conflicts_view(request, species_id: str):
    return ok(id_mapping.get_species_conflicts(species_id, limit=request.GET.get('limit', 100)))


@api_view(['GET'])
def species_phylogeny_context_view(request, species_id: str):
    try:
        return ok(phylogeny.species_context(species_id, release_id=request.GET.get('release_id', '')))
    except phylogeny.PhylogenyNotFound as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def entity_id_mapping_view(request, species_id: str, entity_key: str):
    return ok(id_mapping.get_entity_mapping_chain(species_id, entity_key))


@api_view(['GET'])
def case2_id_mapping_view(request):
    try:
        return ok(id_mapping.case2_id_mapping_payload())
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def case2_function_chain_view(request):
    try:
        return ok(function_annotations.case2_function_chain_payload())
    except function_annotations.AnnotationNotFound as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def case3_function_evidence_view(request):
    try:
        return ok(function_annotations.case3_function_evidence_payload())
    except function_annotations.AnnotationNotFound as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def annotation_status_view(request):
    return ok(function_annotations.annotation_status_payload(
        query=request.GET.get('query') or request.GET.get('q') or '',
        species_id=request.GET.get('species_id', ''),
        page=request.GET.get('page', 1),
        page_size=request.GET.get('page_size', 50),
    ))


@api_view(['GET'])
def annotation_search_view(request):
    return ok(function_annotations.annotation_search_payload(
        query=request.GET.get('query') or request.GET.get('q') or '',
        species_id=request.GET.get('species_id', ''),
        limit=request.GET.get('limit', 25),
    ))


@api_view(['GET'])
def species_functional_summary_view(request, species_id: str):
    return ok(function_annotations.species_functional_summary(species_id))


@api_view(['GET'])
def species_go_annotations_view(request, species_id: str):
    return ok(function_annotations.go_annotations_payload(
        species_id,
        namespace=request.GET.get('namespace', ''),
        query=request.GET.get('query') or request.GET.get('q') or '',
        page=request.GET.get('page', 1),
        page_size=request.GET.get('page_size', 50),
    ))


@api_view(['GET'])
def species_kegg_annotations_view(request, species_id: str):
    return ok(function_annotations.kegg_annotations_payload(
        species_id,
        annotation_type=request.GET.get('annotation_type', ''),
        query=request.GET.get('query') or request.GET.get('q') or '',
        page=request.GET.get('page', 1),
        page_size=request.GET.get('page_size', 50),
    ))


@api_view(['GET'])
def entity_function_view(request, species_id: str, entity_key: str):
    return ok(function_annotations.entity_function_payload(species_id, entity_key))


@api_view(['POST'])
def functional_enrichment_view(request):
    try:
        return ok(function_annotations.enrichment_payload(request.data or {}))
    except function_annotations.AnnotationNotFound as exc:
        return err(str(exc), status=400)


@api_view(['GET'])
def quality_view(request):
    return ok(services.quality_overview())


@api_view(['GET'])
def quality_species_view(request, species_id: str):
    try:
        return ok(services.quality_species(species_id))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def species_collection(request):
    return ok(services.list_species(
        query=request.GET.get('query', ''),
        domain=request.GET.get('domain', ''),
        omics=request.GET.get('omics', ''),
        clade=request.GET.get('clade', ''),
        habitat=request.GET.get('habitat', ''),
        has_all_omics=request.GET.get('has_all_omics', ''),
        genome_size_min=request.GET.get('genome_size_min', ''),
        genome_size_max=request.GET.get('genome_size_max', ''),
        fingerprint_filters=request.GET.get('fingerprint_filters', ''),
        sort_by=request.GET.get('sort_by', 'display_name'),
        sort_order=request.GET.get('sort_order', 'asc'),
        page=request.GET.get('page', ''),
        page_size=request.GET.get('page_size', request.GET.get('limit', '')),
        compare_default=request.GET.get('compare_default', ''),
        include_aggregate=request.GET.get('include_aggregate', 'true'),
    ))


@api_view(['GET'])
def species_atlas_summary_view(request):
    return ok(services.species_atlas_summary(
        query=request.GET.get('query', ''),
        domain=request.GET.get('domain', ''),
        clade=request.GET.get('clade', ''),
        habitat=request.GET.get('habitat', ''),
        genome_size_min=request.GET.get('genome_size_min', ''),
        genome_size_max=request.GET.get('genome_size_max', ''),
        fingerprint_filters=request.GET.get('fingerprint_filters', ''),
    ))


@api_view(['GET'])
def facets_view(request):
    return ok(services.species_facets())



@api_view(['GET'])
def species_detail_view(request, species_id: str):
    try:
        lightweight = str(request.GET.get('lightweight', '')).lower() in {'1', 'true', 'yes', 'on'}
        return ok(services.species_detail(species_id, lightweight=lightweight))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def species_enhanced_view(request, species_id: str):
    try:
        return ok(services.species_enhanced_visuals(species_id, compute=request.GET.get('compute', 'stored')))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)




@api_view(['GET'])
def omics_bundle_view(request, species_id: str, omics: str):
    try:
        return ok(services.get_omics_bundle(species_id, omics, scope=request.GET.get('scope', 'core'), compute=request.GET.get('compute', 'stored')))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def omics_summary_view(request, species_id: str, omics: str):
    try:
        return ok(services.get_summary(species_id, omics, scope=request.GET.get('scope', 'core'), compute=request.GET.get('compute', 'stored')))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def omics_analysis_view(request, species_id: str, omics: str):
    try:
        return ok(services.get_analysis(species_id, omics, scope=request.GET.get('scope', 'core'), compute=request.GET.get('compute', 'stored')))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def omics_rows_view(request, species_id: str, omics: str):
    try:
        data = services.row_listing(
            species_id,
            omics,
            query=request.GET.get('query', ''),
            strategy_cluster=request.GET.get('strategy_cluster', ''),
            sort_by=request.GET.get('sort_by', ''),
            sort_order=request.GET.get('sort_order', 'desc'),
            page=request.GET.get('page', 1),
            page_size=request.GET.get('page_size', 25),
            feature_filters=request.GET.get('feature_filters', ''),
            scope=request.GET.get('scope', 'core'),
        )
        return ok(data)
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def omics_row_detail_view(request, species_id: str, omics: str, entity_id: str):
    try:
        return ok(services.row_detail(species_id, omics, entity_id, scope=request.GET.get('scope', 'core')))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def omics_field_summary_view(request, species_id: str, omics: str):
    try:
        return ok(
            services.field_summary(
                species_id,
                omics,
                field=request.GET.get('field', ''),
                scope=request.GET.get('scope', 'core'),
                compute=request.GET.get('compute', 'stored'),
            )
        )
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def omics_scatter_view(request, species_id: str, omics: str):
    try:
        return ok(
            services.scatter_payload(
                species_id,
                omics,
                x_field=request.GET.get('x', ''),
                y_field=request.GET.get('y', ''),
                scope=request.GET.get('scope', 'core'),
                sample=request.GET.get('sample', 1200),
                compute=request.GET.get('compute', 'stored'),
            )
        )
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def compare_view(request):
    ids = [x.strip() for x in request.GET.get('species_ids', '').split(',') if x.strip()]
    omics = request.GET.get('omics', '')
    normalization = request.GET.get('normalization', 'robust_zscore')
    adjustment = request.GET.get('adjustment', 'none')
    distance = request.GET.get('distance', 'euclidean')
    group_by = request.GET.get('group_by', '')
    detail = request.GET.get('detail', 'light')
    try:
        return ok(
            services.compare_species(
                ids,
                omics=omics,
                normalization=normalization,
                adjustment=adjustment,
                distance=distance,
                group_by=group_by,
                detail=detail,
            )
        )
    except services.NotFoundError as exc:
        return err(str(exc), status=404)
    except ValueError as exc:
        return err(str(exc), status=400)


@api_view(['GET'])
def cross_omics_view(request, species_id: str):
    try:
        return ok(services.get_cross_omics(species_id, compute=request.GET.get('compute', 'stored')))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def guide_view(request):
    return ok(services.guide_payload())


@api_view(['GET'])
def contact_view(request):
    return ok(services.contact_payload())


@api_view(['GET'])
def downloads_view(request):
    return ok(services.downloads_manifest(
        species_id=request.GET.get('species', ''),
        omics=request.GET.get('omics', ''),
        dataset_limit=request.GET.get('dataset_limit', ''),
        artifact_limit=request.GET.get('artifact_limit', ''),
    ))


@api_view(['GET'])
def artifact_registry_view(request):
    try:
        limit = int(request.GET.get('limit', '500') or 500)
    except (TypeError, ValueError):
        limit = 500
    return ok(services.artifact_registry(
        species_id=request.GET.get('species', ''),
        omics=request.GET.get('omics', ''),
        artifact_type=request.GET.get('artifact_type', ''),
        limit=limit,
    ))


@api_view(['POST', 'GET'])
def materialize_artifacts_view(request):
    return ok(services.materialize_analysis_artifacts())


@api_view(['GET'])
def docs_view(request):
    return ok(services.docs_payload())


@api_view(['GET'])
def meta_view(request):
    home = services.home_payload()
    return ok({
        'omics_meta': services.omics_meta(),
        'feature_display_schema': services.feature_display_schema(),
        'project': home.get('project', {}),
        'platform_scope': home.get('platform_scope', {}),
    })


@api_view(['GET'])
def feature_catalog_view(request):
    return ok(services.feature_catalog_payload())


def _feature_hub_error(exc: FeatureHubError):
    return err(str(exc), status=getattr(exc, "status_code", 400))


@api_view(['GET'])
def feature_hub_overview_view(request):
    try:
        return ok(feature_hub_api.overview())
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['GET'])
def feature_hub_catalog_view(request):
    try:
        return ok(feature_hub_api.catalog(request.GET))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['GET'])
def feature_hub_species_view(request):
    try:
        return ok(feature_hub_api.species(request.GET))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['GET'])
def feature_hub_dataset_view(request, species_id: str, omics: str):
    try:
        return ok(feature_hub_api.dataset_detail(species_id, omics, request.GET))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['GET'])
def feature_hub_preview_view(request):
    try:
        return ok(feature_hub_api.preview(request.GET))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['GET'])
def feature_hub_home_preview_view(request):
    try:
        return ok(feature_hub_api.home_preview(request.GET))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['GET'])
def feature_hub_field_profile_view(request):
    try:
        return ok(feature_hub_api.profile(request.GET))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['POST'])
def feature_hub_qc_view(request):
    try:
        return ok(feature_hub_api.qc(request.data or {}))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['POST'])
def feature_hub_export_create_view(request):
    try:
        return ok(feature_hub_api.create_export_job(request.data or {}))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['GET'])
def feature_hub_export_detail_view(request, export_id: str):
    try:
        return ok(feature_hub_api.get_export(export_id))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['GET'])
def feature_hub_export_download_view(request, export_id: str):
    try:
        path = feature_hub_api.download_export(export_id)
        return FileResponse(path.open('rb'), as_attachment=True, filename=Path(path).name)
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['POST'])
def feature_hub_alignment_view(request):
    try:
        return ok(feature_hub_api.alignment(request.data or {}))
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['POST'])
def feature_hub_registry_build_view(request):
    try:
        return ok(feature_hub_api.build_registry())
    except FeatureHubError as exc:
        return _feature_hub_error(exc)


@api_view(['GET'])
def search_view(request):
    return ok(services.universal_search(request.GET.get('query', ''), limit=request.GET.get('limit', 16)))


@api_view(['GET'])
def download_feature_file_view(request, file_id: str):
    try:
        path = services.resolve_feature_file(file_id)
        return FileResponse(path.open('rb'), as_attachment=True, filename=Path(path).name)
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def download_artifact_file_view(request, artifact_id: str):
    try:
        path = services.resolve_artifact_file(artifact_id)
        return FileResponse(path.open('rb'), as_attachment=True, filename=Path(path).name)
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def download_id_mapping_view(request):
    try:
        path = id_mapping.download_path(
            kind=request.GET.get('kind', 'external'),
            species_id=request.GET.get('species_id', ''),
            division=request.GET.get('division', ''),
        )
        return FileResponse(path.open('rb'), as_attachment=True, filename=Path(path).name)
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def download_annotation_view(request, kind: str):
    try:
        path = function_annotations.download_path(kind)
        return FileResponse(path.open('rb'), as_attachment=True, filename=Path(path).name)
    except function_annotations.AnnotationNotFound as exc:
        return err(str(exc), status=404)
