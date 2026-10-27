from __future__ import annotations
import csv
import io
from django.http import HttpResponse
from django.urls import path
from django.views.decorators.gzip import gzip_page
from rest_framework.decorators import api_view, content_negotiation_class
from rest_framework.negotiation import DefaultContentNegotiation
from backend.apps.common.responses import err, ok
from . import artifacts
from .aggregates import build_payload
from .contracts import OMICS, normalize_filters


def _global_only(params):
    filters = normalize_filters(params)
    if any(v for v in filters.values() if v is not None):
        raise ValueError("Home visuals describe the full registry/schema and do not accept context filters.")


@gzip_page
@api_view(["GET"])
def home_visuals(request):
    try:
        _global_only(request.query_params)
        return ok(build_payload("home", request.query_params))
    except ValueError as exc:
        return err(str(exc))
    except OSError:
        return err("Chart metadata is unreadable; other home modules remain available.", status=503)


@gzip_page
@api_view(["GET"])
def atlas_visuals(request):
    try:
        return ok(build_payload("atlas", request.query_params))
    except ValueError as exc:
        return err(str(exc))
    except OSError:
        return err("Diagnostic metadata is unreadable; the species registry remains available.", status=503)


def export_rows(card, detail="matrix"):
    data, code = card["data"], card["chart_id"]
    if code == "H1":
        return data["groups"]
    if code == "H2":
        return data["links"]
    if code == "H3":
        return data["fields"]
    if code == "D1":
        return [{"group": r["group"], "omics": m, "species_count": r["species_count"], **r["layers"][m]}
                for r in data["rows"] for m in OMICS]
    if code == "D2":
        return [{"group": r["group"], "n_source": r["n_source"], "n_excluded": r["n_excluded"], **point}
                for r in data["groups"] for point in r["points"]]
    if code == "D3":
        background = {f'core_ready_{r["n_ready_layers"]}': r["n_species"] for r in data["core_ready_counts"]}
        return [{**r, **background, "full_basis": data["full_basis"]} for r in data["full_patterns"]]
    if code == "D4":
        rows = [{"record_type": "source_method", **r} for r in data["source_counts"]]
        for layer in data["layers"]:
            curve = layer["ecdf"]
            if curve:
                rows.extend({"record_type": "ecdf_frequency", "omics": layer["omics"],
                             "missing_cells": x, "frequency": n, "cdf": p, "denominator": layer["n_summary"]}
                            for x, n, p in zip(curve["x_missing_cells"], curve["frequency"], curve["cdf"]))
        return rows
    if detail != "fields":
        return data["cells"]
    rows = []
    for cell in data["cells"]:
        if cell["status"] != "ready":
            rows.append({k: cell[k] for k in ("sid", "species_id", "omics", "status", "reason")})
            continue
        # Immutable object identity is pinned in the card, even if a manifest is published concurrently.
        identity = cell["artifact_id"]
        obj = artifacts.diagnostic({"object_file": identity + ".json", "object_sha256": identity})
        for profile in obj["profiles"] + obj["metadata_profiles"]:
            rows.append({"sid": cell["sid"], "species_id": cell["species_id"], **profile,
                         "source_sha256": cell["source_sha256"], "artifact_version": cell["artifact_version"]})
    return rows


def _safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class ExportContentNegotiation(DefaultContentNegotiation):
    def filter_renderers(self, renderers, format):
        # This endpoint owns ?format=csv/tsv. DRF's global JSON suffix override
        # would otherwise reject valid downloads before the view can run.
        return renderers


@api_view(["GET"])
@content_negotiation_class(ExportContentNegotiation)
def export_visuals(request):
    code = str(request.query_params.get("chart_id", "")).upper()
    fmt = request.query_params.get("format", "csv")
    detail = request.query_params.get("detail", "matrix")
    if code not in {"H1", "H2", "H3", "D1", "D2", "D3", "D4", "D5"} or fmt not in {"csv", "tsv"} or detail not in {"matrix", "fields"}:
        return err("Invalid chart_id, format or detail.")
    try:
        if code.startswith("H"):
            _global_only(request.query_params)
        payload = build_payload("home" if code.startswith("H") else "atlas", request.query_params)
        expected = request.query_params.get("expected_source_revision") or request.query_params.get("source_revision")
        if expected and expected != payload["meta"]["source_revision"]:
            return err("refresh_required", status=409, details={"source_revision": payload["meta"]["source_revision"]})
        rows = export_rows(payload["cards"][code], detail)
        common = {k: payload["meta"][k] for k in ("scope_id", "source_revision")}
        common["chart_id"] = code
        common["applied_filters"] = __import__("json").dumps(payload["meta"]["applied_filters"], ensure_ascii=False, sort_keys=True)
        common["ignored_for_context"] = __import__("json").dumps(payload["meta"]["ignored_for_context"], ensure_ascii=False, sort_keys=True)
        rows = [{**common, **r} for r in rows]
        columns = list(dict.fromkeys(k for r in rows for k in r)) or list(common)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=columns, delimiter="," if fmt == "csv" else "\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _safe_cell(v) for k, v in row.items()})
        response = HttpResponse(buffer.getvalue(), content_type=("text/csv" if fmt == "csv" else "text/tab-separated-values") + "; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="home_atlas_{code}.{fmt}"'
        response["X-Source-Revision"] = payload["meta"]["source_revision"]
        return response
    except ValueError as exc:
        return err(str(exc))
    except (OSError, KeyError):
        return err("Pinned diagnostic artifact unavailable; refresh and retry.", status=409)


urlpatterns = [
    path("home/visuals/", home_visuals),
    path("species/atlas-visuals/", atlas_visuals),
    path("visuals/home-atlas/export/", export_visuals),
]
