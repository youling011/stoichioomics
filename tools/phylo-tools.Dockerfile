FROM mambaorg/micromamba:1.5.10

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash coreutils findutils procps \
    && rm -rf /var/lib/apt/lists/*
USER $MAMBA_USER

RUN micromamba install -y -n base -c conda-forge -c bioconda \
      python=3.11 \
      busco \
      orthofinder \
      mafft \
      clipkit \
      iqtree \
      diamond \
      blast \
      fasttree \
    && micromamba clean --all --yes

ENV PATH=/opt/conda/bin:$PATH
WORKDIR /work
