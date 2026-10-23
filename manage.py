#!/usr/bin/env python
import os
import sys


def main():
    # These explicit producers already parallelize by species; avoid allocating a
    # separate native BLAS thread pool in every CLI parent and child process.
    if len(sys.argv)>1 and sys.argv[1] in {'materialize_proteome_visuals','audit_proteome_visuals','materialize_sequence_visuals', 'materialize_integration_visuals'}:
        for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
            os.environ[name]='1'
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
