from django.urls import path
from .views import (
    hvg_summary, hvg_phase1_summary, hvg_phase2_summary, hvg_phase2_model, hvg_plots,
    hvg_genes, hvg_gene_detail, hvg_download, hvg_group_comparison_summary,
    hvg_group_comparison_features, hvg_group_comparison_feature_detail,
)
urlpatterns = [
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
