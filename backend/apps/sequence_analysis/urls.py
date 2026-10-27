from django.urls import path

from . import views

from .visuals_views import urlpatterns as workflow_visuals_urls
urlpatterns = [
    *workflow_visuals_urls,
    path('jobs/', views.jobs_view),
    path('prevalidate/', views.prevalidate_view),
    path('sample-sheet-template/', views.sample_sheet_template_view),
    path('jobs/<str:job_id>/', views.job_detail_view),
    path('jobs/<str:job_id>/logs/', views.job_logs_view),
    path('jobs/<str:job_id>/reproducibility/', views.job_reproducibility_view),
    path('jobs/<str:job_id>/job-manifest/', views.job_manifest_view),
    path('jobs/<str:job_id>/input-qc/', views.input_qc_view),
    path('jobs/<str:job_id>/analysis-design/', views.analysis_design_view),
    path('jobs/<str:job_id>/result-interpretation/', views.result_interpretation_view),
    path('jobs/<str:job_id>/download-manifest/', views.download_manifest_view),
    path('jobs/<str:job_id>/features/', views.features_view),
    path('jobs/<str:job_id>/differential-features/', views.differential_features_view),
    path('jobs/<str:job_id>/differential-entities/', views.differential_entities_view),
    path('jobs/<str:job_id>/plots/', views.plots_view),
    path('jobs/<str:job_id>/platform/', views.platform_bundle_view),
    path('jobs/<str:job_id>/analysis/', views.analysis_payload_view),
    path('jobs/<str:job_id>/feature-catalog/', views.feature_catalog_view),
    path('jobs/<str:job_id>/feature-summary/', views.feature_summary_view),
    path('jobs/<str:job_id>/basic-visualization/', views.basic_visualization_view),
    path('jobs/<str:job_id>/core-feature-panels/', views.core_feature_panels_view),
    path('jobs/<str:job_id>/top-low/', views.top_low_view),
    path('jobs/<str:job_id>/comparison/sample/', views.sample_comparison_view),
    path('jobs/<str:job_id>/ml-discrimination/', views.ml_discrimination_view),
    path('jobs/<str:job_id>/field-summary/', views.field_summary_view),
    path('jobs/<str:job_id>/scatter/', views.scatter_view),
    path('jobs/<str:job_id>/comparison/feature/', views.feature_comparison_view),
    path('jobs/<str:job_id>/comparison/entities/', views.entity_comparison_view),
    path('jobs/<str:job_id>/table-export/<str:kind>/', views.table_export_view),
    path('jobs/<str:job_id>/download/<str:kind>/', views.download_view),
]
