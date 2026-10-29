from django.urls import path
from .views import (
    hvg_summary, hvg_phase1_summary, hvg_phase2_summary, hvg_phase2_model, hvg_plots,
    hvg_genes, hvg_gene_detail, hvg_download, hvg_group_comparison_summary,
    hvg_group_comparison_features, hvg_group_comparison_feature_detail,
)
from .research_views import research_endpoint
from .visuals_views import urlpatterns as workflow_visuals_urls
from .manifest_views import urlpatterns as result_manifest_urls
urlpatterns = [
    *result_manifest_urls,
    *workflow_visuals_urls,
    path('<str:identifier>/research/<str:endpoint>/', research_endpoint),
    path('<str:identifier>/research/<str:endpoint>/<path:object_id>/', research_endpoint),
    path('<str:identifier>/summary/', hvg_summary),
    path('<str:identifier>/phase1-summary/', hvg_phase1_summary),
    path('<str:identifier>/phase2-summary/', hvg_phase2_summary),
    path('<str:identifier>/phase2-model/', hvg_phase2_model),
    path('<str:identifier>/plots/', hvg_plots),
    path('<str:identifier>/genes/', hvg_genes),
    path('<str:identifier>/genes/<str:gene_id>/', hvg_gene_detail),
    path('<str:identifier>/group-comparison/summary/', hvg_group_comparison_summary),
    path('<str:identifier>/group-comparison/features/', hvg_group_comparison_features),
    path('<str:identifier>/group-comparison/features/<str:feature_key>/', hvg_group_comparison_feature_detail),
    path('<str:identifier>/download/<str:kind>/', hvg_download),
]
