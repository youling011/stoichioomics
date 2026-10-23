"""Keep NumPy binning unchanged except for an unrepresentable bin width."""
import numpy as np


def finite_histogram(values, bins):
    try:
        return np.histogram(values, bins=bins)
    except ValueError as exc:
        if 'Too many bins for data range' not in str(exc):
            raise
        # Adjacent floating-point values cannot form the requested finite edges.
        # A single bin retains every observation without rounding source values.
        return np.histogram(values, bins=1)
