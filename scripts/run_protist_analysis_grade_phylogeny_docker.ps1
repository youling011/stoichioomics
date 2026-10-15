param(
  [int]$Threads = 20,
  [string]$RunLabel = "orthofinder_subset30_run_20260717"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Image = "stoich-phylo-tools:local"
$ProteomeDir = "data/phylogeny/protist_phylogeny_v1/stage7_analysis_grade/subset30/orthofinder_proteomes"
$SubsetTraitMatrix = "data/phylogeny/protist_phylogeny_v1/stage7_analysis_grade/subset30/species_trait_matrix_subset30.csv"
$OutDir = "data/phylogeny/protist_phylogeny_v1/stage7_analysis_grade/$RunLabel"
$SupermatrixDir = "data/phylogeny/protist_phylogeny_v1/stage7_analysis_grade/subset30_iqtree_supermatrix_pipeline"

Set-Location $ProjectRoot

docker build -t $Image -f tools/phylo-tools.Dockerfile .

docker run --rm $Image bash -lc 'export PATH=/opt/conda/bin:$PATH; busco --version; orthofinder -h | head -n 2; mafft --version 2>&1 | head -n 1; clipkit --version; iqtree --version | head -n 2; diamond version | head -n 1'

python scripts/prepare_protist_phylogeny_subset30.py --force

if (Test-Path $OutDir) {
  throw "Output directory already exists: $OutDir. Choose a new -RunLabel or remove/archive the previous run."
}

docker run --name stoich_orthofinder_subset30 --rm `
  -v "${ProjectRoot}:/work" `
  -w /work `
  $Image `
  bash -lc "export PATH=/opt/conda/bin:`$PATH; orthofinder -f $ProteomeDir -t $Threads -o $OutDir"

docker run --rm `
  -v "${ProjectRoot}:/work" `
  -w /work `
  $Image `
  bash -lc "export PATH=/opt/conda/bin:`$PATH; python scripts/build_protist_iqtree_supermatrix_from_orthofinder.py --orthofinder-results $OutDir/Results_* --trait-matrix $SubsetTraitMatrix --out-dir $SupermatrixDir --min-taxon-fraction 0.5 --max-loci 80 --balance-min-loci-per-species 5 --mafft-mode fast --iqtree-model LG+G4 --threads $Threads --bootstrap 1000"

python scripts/register_protist_analysis_grade_tree.py --tree "$SupermatrixDir/final/protist_iqtree.treefile" --trait-matrix $SubsetTraitMatrix --source subset30_orthofinder_selected_orthogroups_mafft_fast_clipkit_iqtree_lg_g4 --allow-subset
