<template>
  <div class="stack-lg">
    <section class="hero-panel hub-hero">
      <div class="hero-copy">
        <div class="eyebrow">User workflow center</div>
        <h1>Run analyses on user-owned data</h1>
        <p>
          User workflows are grouped into two major branches: uploaded sequence stoichiometric analysis and
          Expression/HVG Stoich Extension analysis. These runtime workflows are separate from the curated species database.
        </p>
      </div>
      <div class="panel hub-note">
        <div class="eyebrow">Privacy model</div>
        <p class="muted">
          Uploaded sequence inputs are used for runtime computation and are not imported into the public species registry.
          Derived results remain temporary according to the configured cleanup policy.
        </p>
      </div>
    </section>

    <section class="workflow-major-grid">
      <router-link class="feature-card workflow-major-card" to="/sequence-analysis">
        <div class="eyebrow">Workflow branch 1</div>
        <h3>Uploaded sequence stoichiometry</h3>
        <p class="muted">
          Upload genome, transcript sequence, or proteome FASTA inputs; compute stoichiometric features; inspect database-style
          visualization, deep analysis, custom comparisons, differential features, and differential genes or records.
        </p>
        <div class="hub-card-footer">
          <span class="badge">FASTA based</span>
          <span class="ghost-link">Open sequence workflow</span>
        </div>
      </router-link>

      <router-link class="feature-card workflow-major-card" to="/hvg-workflow">
        <div class="eyebrow">Workflow branch 2</div>
        <h3>Expression/HVG Stoich Extension</h3>
        <p class="muted">
          Use an expression matrix plus metadata together with stoichiometric feature tables to inspect HVG classes,
          residual signals, feature associations, and saved extension cases.
        </p>
        <div class="hub-card-footer">
          <span class="badge">Expression based</span>
          <span class="ghost-link">Open Expression/HVG workflow</span>
        </div>
      </router-link>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Related workflow pages</div>
          <h3>Secondary entrances</h3>
        </div>
      </div>
      <div class="hub-link-strip">
        <router-link class="side-nav-link" to="/hvg-compare">Expression/HVG compare</router-link>
        <router-link class="side-nav-link" to="/registry">Expression/HVG registry</router-link>
        <router-link class="side-nav-link" to="/jobs">Legacy job list</router-link>
        <router-link class="side-nav-link" to="/create">Generic job creation</router-link>
      </div>
    </section>
  </div>
</template>
