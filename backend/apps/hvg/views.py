from django.http import FileResponse
from rest_framework.decorators import api_view

from backend.apps.common.responses import ok, err
from .services import (
    get_phase1_summary,
    get_phase2_summary,
    get_phase2_model,
    get_plots,
    get_genes,
    get_gene_detail,
    get_downloadable_file,
    get_group_comparison_summary,
    get_group_comparison_features,
    get_group_comparison_feature_detail,
)


@api_view(["GET"])
def hvg_summary(request, identifier: str):
    try:
        return ok({
            "phase1": get_phase1_summary(identifier),
            "phase2": get_phase2_summary(identifier),
        })
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_phase1_summary(request, identifier: str):
    try:
        return ok(get_phase1_summary(identifier))
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_phase2_summary(request, identifier: str):
    try:
        return ok(get_phase2_summary(identifier))
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_phase2_model(request, identifier: str):
    try:
        return ok(get_phase2_model(identifier))
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_plots(request, identifier: str):
    try:
        return ok(get_plots(identifier))
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_genes(request, identifier: str):
    try:
        page = int(request.GET.get("page", "1"))
        page_size = int(request.GET.get("page_size", "50"))
        sort_by = request.GET.get("sort_by")
        sort_order = request.GET.get("sort_order", "desc")

        filters = {
            "stoich_class": request.GET.get("stoich_class") or None,
            "stoich_associated_feature": request.GET.get("stoich_associated_feature") or request.GET.get("stoich_" + "driver") or None,
            "gene_query": request.GET.get("gene_query") or None,
        }

        payload = get_genes(
            identifier,
            filters=filters,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return ok(payload)
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_gene_detail(request, identifier: str, gene_id: str):
    try:
        return ok(get_gene_detail(identifier, gene_id))
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_group_comparison_summary(request, identifier: str):
    try:
        return ok(get_group_comparison_summary(identifier))
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_group_comparison_features(request, identifier: str):
    try:
        filters = {
            "omics": request.GET.get("omics") or None,
            "family": request.GET.get("family") or None,
            "evidence": request.GET.get("evidence") or None,
            "direction": request.GET.get("direction") or None,
            "status": request.GET.get("status") or None,
            "analysis_status": request.GET.get("analysis_status") or None,
            "adjustment": request.GET.get("adjustment") or None,
            "significant": request.GET.get("significant") or None,
            "missing_rate": request.GET.get("missing_rate") or None,
            "search": request.GET.get("search") or None,
        }
        return ok(get_group_comparison_features(
            identifier,
            filters=filters,
            page=int(request.GET.get("page", "1")),
            page_size=int(request.GET.get("page_size", "50")),
            sort_by=request.GET.get("sort_by", "abs_effect"),
            sort_order=request.GET.get("sort_order", "desc"),
        ))
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except (TypeError, ValueError) as e:
        return err(str(e), status=400)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_group_comparison_feature_detail(request, identifier: str, feature_key: str):
    try:
        return ok(get_group_comparison_feature_detail(identifier, feature_key))
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)


@api_view(["GET"])
def hvg_download(request, identifier: str, kind: str):
    try:
        path = get_downloadable_file(identifier, kind)
        return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name)
    except FileNotFoundError as e:
        return err(str(e), status=404)
    except Exception as e:
        return err(str(e), status=500)
