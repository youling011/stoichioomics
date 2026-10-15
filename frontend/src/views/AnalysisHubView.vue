<template>
  <div class="stack-lg">
    <section v-if="loading" class="panel">
      <p class="muted">Loading analysis hub payload...</p>
    </section>

    <section v-else-if="loadError" class="panel">
      <p class="muted">{{ loadError }}</p>
      <button class="btn subtle" @click="load">Retry</button>
    </section>

    <template v-else-if="payload">
      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Stage 4 real-result modules</div>
            <h3>Omics-internal, cross-omics, and cross-species analysis</h3>
            <p class="muted">This hub now separates reproducible real-result analyses from exploratory analyses. Real-result modules are directly generated from the imported stoichiometric registry and persisted payloads.</p>
          </div>
          <span class="badge">{{ payload.release.database_engine }} / {{ payload.release.label }}</span>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">10. Omics-internal real analysis</div>
            <h3>Selected omics: {{ selectedOmics }}</h3>
          </div>
        </div>
        <div class="toolbar-grid">
          <select v-model="selectedOmics" class="input">
            <option value="genome">Genome</option>
            <option value="transcriptome">Transcript sequence</option>
            <option value="proteome">Proteome</option>
          </select>
        </div>
        <div class="grid grid-2">
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Strategy composition</h3></div>
            <EChart :option="omicsStrategyChart" :height="340" />
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Feature ranking by mean value</h3></div>
            <EChart :option="omicsFeatureRankChart" :height="340" />
          </article>
        </div>
        <div class="grid grid-2">
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Outlier count distribution</h3></div>
            <EChart :option="omicsOutlierChart" :height="320" />
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Tradeoff-score distribution</h3></div>
            <EChart :option="omicsTradeoffChart" :height="320" />
          </article>
        </div>
        <article class="panel chart-panel">
          <div class="section-header compact"><h3>Omics-specific module</h3></div>
          <EChart :option="omicsSpecificChart" :height="360" />
        </article>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">11. Global Cross-omics Atlas</div>
            <h3>X1/X7 global resource shift and concordance</h3>
          </div>
        </div>
        <div class="metric-band" style="margin-bottom: 12px">
          <span class="badge">All species {{ crossBlock.join_coverage?.all_species || 0 }}</span>
          <span class="badge">All omics loaded {{ crossBlock.join_coverage?.all_omics_loaded || 0 }}</span>
          <span class="badge">Shift pairs {{ crossBlock.pair_count || 0 }}</span>
          <span class="badge">Scope: top_transformations atlas</span>
        </div>
        <div class="grid grid-2">
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Global X1 DNA-to-RNA vs RNA-to-protein shifts</h3></div>
            <EChart :option="crossShiftScatterChart" :height="360" />
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Global concordance and conserved/shifted</h3></div>
            <EChart :option="crossConcordanceChart" :height="170" />
            <EChart :option="crossConservedChart" :height="170" />
          </article>
        </div>
        <div class="grid grid-3">
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>X1 DNA-to-RNA histogram</h3></div>
            <EChart :option="dnaToRnaHistChart" :height="300" />
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>X1 RNA-to-protein histogram</h3></div>
            <EChart :option="rnaToProteinHistChart" :height="300" />
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>X8 global species event ranking</h3></div>
            <EChart :option="crossEventRankChart" :height="300" />
          </article>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">12. Cross-species real comparative analysis</div>
            <h3>Effect-size and discriminative-feature modules</h3>
          </div>
        </div>
        <div class="grid grid-3">
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Effect sizes</h3></div>
            <EChart :option="crossSpeciesEffectChart" :height="320" />
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Discriminative features (std)</h3></div>
            <EChart :option="crossSpeciesDiscriminativeChart" :height="320" />
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Pairwise distance distribution</h3></div>
            <EChart :option="crossSpeciesDistanceChart" :height="320" />
          </article>
        </div>
      </section>

      <PhylogenyInsightPanel
        title="P3 phylogeny-aware runtime results"
        subtitle="Runtime Pagel lambda and OLS/PGLS use the registered subset30 branch-length tree; descriptive modules remain available for species outside that tree."
      />

      <section v-if="payload.real?.functional_annotations" class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Functional annotations</div>
            <h3>GO/KEGG evidence and enrichment-ready universes</h3>
            <p class="muted">{{ payload.real.functional_annotations.method_metadata?.method }}</p>
          </div>
          <router-link class="btn subtle" to="/downloads">Download files</router-link>
        </div>
        <div class="grid grid-4">
          <div class="card">
            <div class="label">Species tracked</div>
            <div class="kpi">{{ payload.real.functional_annotations.summary?.species_total }}</div>
          </div>
          <div class="card">
            <div class="label">GO species</div>
            <div class="kpi">{{ payload.real.functional_annotations.summary?.go_species_count }}</div>
          </div>
          <div class="card">
            <div class="label">KEGG species</div>
            <div class="kpi">{{ payload.real.functional_annotations.summary?.kegg_species_count }}</div>
          </div>
          <div class="card">
            <div class="label">GO rows</div>
            <div class="kpi">{{ payload.real.functional_annotations.summary?.go_annotation_count }}</div>
          </div>
        </div>
        <div class="badge-row compact-top">
          <span v-for="endpoint in payload.real.functional_annotations.endpoints || []" :key="endpoint" class="badge muted-badge">{{ endpoint }}</span>
        </div>
      </section>

      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">13. Exploratory analysis modules</div>
            <h3>Explicitly labeled hypothesis-generating branch</h3>
            <p class="muted">{{ payload.exploratory.disclaimer }}</p>
          </div>
          <span class="badge">Exploratory</span>
        </div>
        <div class="grid grid-2">
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Exploratory embedding</h3></div>
            <EChart :option="exploratoryEmbeddingChart" :height="360" />
            <MethodBadge
              :method="payload.exploratory.method || payload.exploratory.method_metadata?.method || 'pca_svd'"
              :normalization="payload.exploratory.method_metadata?.normalization"
              :missing-policy="payload.exploratory.method_metadata?.missing_policy"
              :n="payload.exploratory.method_metadata?.n_entities"
              :n-features="payload.exploratory.method_metadata?.n_features"
              :thresholds="payload.exploratory.method_metadata?.thresholds"
              exploratory
              :note="exploratoryVarianceNote"
            />
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Anomaly candidates</h3></div>
            <EChart :option="exploratoryAnomalyChart" :height="360" />
          </article>
        </div>
        <div class="grid grid-2">
          <article class="panel chart-panel">
            <div class="section-header compact"><h3>Exploratory communities</h3></div>
            <EChart :option="exploratoryCommunityChart" :height="320" />
          </article>
          <article class="panel">
            <div class="section-header compact"><h3>Exploratory loadings</h3></div>
            <div class="table-wrap">
              <table class="table compact-table">
                <thead>
                  <tr>
                    <th>Axis</th>
                    <th>Feature combination</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in payload.exploratory.feature_loadings || []" :key="row.axis">
                    <td>{{ row.axis }}</td>
                    <td>{{ row.feature }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Future external-data modules</div>
            <h3>Inputs required before biological interpretation</h3>
          </div>
        </div>
        <div class="grid grid-2">
          <EmptyState
            eyebrow="Ecology / environment"
            title="No environmental covariates loaded"
            message="Ecological interpretation requires external metadata; current stoichiometric features alone should not be treated as environmental evidence."
          />
          <EmptyState
            eyebrow="Structure"
            title="No RNA or protein structure correction loaded"
            message="RNA folding and protein structure modules require external tool outputs and are intentionally not simulated."
          />
        </div>
      </section>
    </template>

    <section v-else class="panel">
      <p class="muted">No analysis payload is available.</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import MethodBadge from '../components/MethodBadge.vue'
import PhylogenyInsightPanel from '../components/PhylogenyInsightPanel.vue'
import { getAnalysisHub } from '../api/stoichdb'
import { areaHistOption, buildEnhancedScatterOption, buildOrdinationOption, donutOption, histogramOption, rankLollipopOption } from '../utils/charts'

const payload = ref(null)
const loading = ref(true)
const loadError = ref('')
const selectedOmics = ref('genome')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    payload.value = await getAnalysisHub()
  } catch (error) {
    payload.value = null
    loadError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to load analysis hub payload.'
  } finally {
    loading.value = false
  }
}

const omicsBlock = computed(() =>
  payload.value?.real?.omics_internal?.[selectedOmics.value] || {},
)

const omicsStrategyChart = computed(() =>
  donutOption(omicsBlock.value?.strategy_composition || []),
)

const omicsFeatureRankChart = computed(() =>
  rankLollipopOption(
    (omicsBlock.value?.feature_rank || []).slice(0, 12).map((row) => ({
      name: row.feature,
      value: row.mean,
    })),
    'name',
    'value',
    'Mean',
  ),
)

const omicsOutlierChart = computed(() =>
  histogramOption(omicsBlock.value?.outlier_distribution || { centers: [], counts: [] }, 'Outlier count', 'Datasets'),
)

const omicsTradeoffChart = computed(() =>
  histogramOption(omicsBlock.value?.tradeoff_distribution || { centers: [], counts: [] }, 'Tradeoff score', 'Count'),
)

const omicsSpecificChart = computed(() => {
  const specific = omicsBlock.value?.specific || {}
  if (specific.kind === 'genome_island') {
    return histogramOption(specific.distribution || { centers: [], counts: [] }, 'Island score', 'Count')
  }
  if (specific.kind === 'transcript_motif') {
    return donutOption(specific.composition || [])
  }
  return rankLollipopOption(
    (specific.budget || []).slice(0, 12).map((row) => ({ name: row.name, value: row.value })),
    'name',
    'value',
    'Mean',
  )
})

const crossBlock = computed(() => payload.value?.real?.cross_omics || {})

const crossShiftScatterChart = computed(() =>
  buildEnhancedScatterOption(
    crossBlock.value?.shift_pairs || [],
    'dna_to_rna_n_shift_std',
    'rna_to_protein_n_shift_std',
    'DNA to RNA N shift std',
    'RNA to protein N shift std',
    {
      currentSpeciesId: 'emiliania_huxleyi',
      title: 'Global X1 standardized DNA-RNA-Protein shifts',
      subtitle: 'Dimensionless robust-z deltas; raw cross-denominator differences are excluded from the main visual.',
    },
  ),
)

const dnaToRnaHistChart = computed(() =>
  histogramOption(crossBlock.value?.dna_to_rna_distribution_std || { centers: [], counts: [] }, 'DNA to RNA N shift std (robust-z delta)', 'Count'),
)

const rnaToProteinHistChart = computed(() =>
  histogramOption(crossBlock.value?.rna_to_protein_distribution_std || { centers: [], counts: [] }, 'RNA to protein N shift std (robust-z delta)', 'Count'),
)

const crossConcordanceChart = computed(() =>
  donutOption(crossBlock.value?.concordance || []),
)

const crossConservedChart = computed(() =>
  donutOption(crossBlock.value?.conserved_vs_shifted || []),
)

const crossEventRankChart = computed(() =>
  rankLollipopOption(
    (crossBlock.value?.species_event_rank || []).slice(0, 12).map((row) => ({ name: row.display_name, value: row.events })),
    'name',
    'value',
    'Events',
  ),
)

const speciesBlock = computed(() => payload.value?.real?.cross_species || {})

const crossSpeciesEffectChart = computed(() =>
  rankLollipopOption(
    (speciesBlock.value?.effect_sizes || []).slice(0, 12).map((row) => ({ name: row.feature, value: row.effect_size })),
    'name',
    'value',
    'Effect size',
  ),
)

const crossSpeciesDiscriminativeChart = computed(() =>
  rankLollipopOption(
    (speciesBlock.value?.discriminative_features || []).slice(0, 12).map((row) => ({ name: row.feature, value: row.std })),
    'name',
    'value',
    'Std',
  ),
)

const crossSpeciesDistanceChart = computed(() =>
  histogramOption(speciesBlock.value?.distance_distribution || { centers: [], counts: [] }, 'Distance', 'Count'),
)

const exploratory = computed(() => payload.value?.exploratory || {})

const exploratoryVarianceNote = computed(() => {
  const ratios = exploratory.value?.explained_variance_ratio || []
  if (!ratios.length) return 'Heuristic fallback: no explained variance is available.'
  return `Explained variance PC1 ${(Number(ratios[0] || 0) * 100).toFixed(1)}%, PC2 ${(Number(ratios[1] || 0) * 100).toFixed(1)}%.`
})

const exploratoryAxisNames = computed(() => {
  const ratios = exploratory.value?.explained_variance_ratio || []
  if ((exploratory.value?.method || '') === 'pca_svd' && ratios.length) {
    return [
      `PC1 (${(Number(ratios[0] || 0) * 100).toFixed(1)}%)`,
      `PC2 (${(Number(ratios[1] || 0) * 100).toFixed(1)}%)`,
    ]
  }
  return ['Heuristic axis 1', 'Heuristic axis 2']
})

const exploratoryEmbeddingChart = computed(() =>
  buildOrdinationOption(
    exploratory.value?.embedding || [],
    'axis1',
    'axis2',
    exploratoryAxisNames.value[0],
    exploratoryAxisNames.value[1],
    {
      sizeKey: 'anomaly_score',
      title: 'Exploratory global embedding',
      subtitle: exploratoryVarianceNote.value,
    },
  ),
)

const exploratoryAnomalyChart = computed(() =>
  rankLollipopOption(
    (exploratory.value?.anomaly_candidates || []).slice(0, 12).map((row) => ({ name: row.display_name, value: row.anomaly_score })),
    'name',
    'value',
    'Anomaly score',
  ),
)

const exploratoryCommunityChart = computed(() =>
  donutOption(exploratory.value?.communities || []),
)

onMounted(load)
</script>
