from __future__ import annotations
import math
import numpy as np
from scipy.stats import gaussian_kde
from .contracts import group_name, group_order


def distributions(species):
    output = []
    for group in group_order(r["domain"] for r in species):
        rows = [r for r in species if group_name(r["domain"]) == group]
        good = []
        for row in rows:
            value = row["genome_size_mb"]
            if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
                good.append((row["species_id"], float(value)))
        good.sort()
        raw = np.array([v for _, v in good], dtype=float)
        entry = {"group": group, "n_source": len(rows), "n_valid": len(good),
                 "n_excluded": len(rows) - len(good),
                 "points": [{"species_id": sid, "mb": v, "offset_index": i} for i, (sid, v) in enumerate(good)],
                 "kde": None, "kde_reason": None}
        for name in ("min_mb", "q25_mb", "median_mb", "q75_mb", "max_mb", "whisker_low_mb", "whisker_high_mb"):
            entry[name] = None
        if len(raw):
            low, q25, median, q75, high = np.quantile(raw, [0, .25, .5, .75, 1], method="linear")
            inlier = raw[(raw >= q25 - 1.5 * (q75 - q25)) & (raw <= q75 + 1.5 * (q75 - q25))]
            entry.update(min_mb=float(low), q25_mb=float(q25), median_mb=float(median), q75_mb=float(q75),
                         max_mb=float(high), whisker_low_mb=float(inlier.min()), whisker_high_mb=float(inlier.max()))
            log = np.log10(raw)
            if len(raw) >= 3 and float(log.var()) > 0:
                try:
                    grid = np.linspace(log.min(), log.max(), 240)
                    density = gaussian_kde(log, bw_method="scott")(grid)
                    if np.isfinite(density).all() and density.max() > 0:
                        entry["kde"] = {"space": "log10_Mb", "bw_method": "scott",
                                        "x_mb": (10.0 ** grid).tolist(),
                                        "density_normalized": (density / density.max()).tolist()}
                    else:
                        entry["kde_reason"] = "nonfinite_or_zero_density"
                except (np.linalg.LinAlgError, ValueError):
                    entry["kde_reason"] = "singular_log_space_covariance"
            else:
                entry["kde_reason"] = "fewer_than_three_values_or_constant_log_space"
        else:
            entry["kde_reason"] = "no_finite_positive_Mb"
        output.append(entry)
    return output
