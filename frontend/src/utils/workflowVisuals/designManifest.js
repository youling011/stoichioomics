export const DESIGN_REVISION=3
export const designManifest={
  "S01": {
    "code": "S01",
    "title": "全部保存字段状态总览",
    "target_design": "全部原保存字段按列顺序的离散状态条带，元数据/全空/常量/变异/非数值分别编码；数量在图注而非另做大柱。",
    "target_location": "basic原family位置；Core各面板的辅助审计；与catalog全数值图谱互补。",
    "specific_acceptance": "每列恰一主要状态，状态色固定离散；单任务不拼入其他任务的三组学。",
    "sources": [
      "seqP_sequence_features",
      "seqG_sequence_features",
      "seqT_sequence_features"
    ]
  },
  "S02": {
    "code": "S02",
    "title": "全部分析特征的组间分位画像",
    "target_design": "全部分析特征×实际组别的分位矩阵，使用固定0..1顺序色标；原值中位数、单位和n在tooltip。",
    "target_location": "overview.featureProfileOption；当前任务适用分析特征，保留原组筛选。",
    "specific_acceptance": "每字段独立参考ECDF；组中位数的位置为count(reference<=median)/n_ref，所有比较声明reference filters。",
    "sources": [
      "seqP_feature_summary",
      "seqG_feature_summary",
      "seqT_feature_summary",
      "seqP_sequence_features",
      "seqG_sequence_features",
      "seqT_sequence_features"
    ]
  },
  "S03": {
    "code": "S03",
    "title": "全量保存PCA坐标展示",
    "target_design": "全量保存PCA点云，实际group配色和每组计数，低透明度小点；超大任务可全量密度并保留组别信息。",
    "target_location": "overview.pcaOption原卡。",
    "specific_acceptance": "保存pc1/pc2逐点与身份一致；缺完整坐标时说明，不能以预览当全点；解释方差仅有保存时显示。",
    "sources": [
      "seqP_plots_payload",
      "seqG_plots_payload",
      "seqT_plots_payload"
    ]
  },
  "S04": {
    "code": "S04",
    "title": "完整差异特征结果及推断可用性",
    "target_design": "全部保存差异特征的排序证据轮廓；使用实际保存importance/效应/统计量，p与q可用数量写在辅助行。",
    "target_location": "overview.topDiffOption；diff_features保留原表与跳转。",
    "specific_acceptance": "差异特征72/73/216仅固定快照；没有p/q时不制造火山图；比较族分别呈现。",
    "sources": [
      "seqP_differential_features",
      "seqG_differential_features",
      "seqT_differential_features"
    ]
  },
  "S05": {
    "code": "S05",
    "title": "完整基因组坐标与序列组成",
    "target_design": "每物种或组的累计注释位置×外显子GC全量hexbin；轮廓和计数色条保留尾部及坐标有效数。",
    "target_location": "Core genome_region_quality的基因组背景局部视图；仅有真实Full坐标才启用。",
    "specific_acceptance": "按实际seqid稳定排序及已保存坐标构造累计注释跨度；没有contig总长时轴名不能称完整组装染色体长度。",
    "sources": [
      "seqG_sequence_features"
    ]
  },
  "S06": {
    "code": "S06",
    "title": "转录序列完整64密码子组成",
    "target_design": "全部64密码子×组别的组成矩阵，原频率单位，稳定字母序；每个codon有位置。",
    "target_location": "基因组genome_cds_codon_usage使用DNA扩展；转录组transcriptome_orf_translated_aa中RNA Full扩展。",
    "specific_acceptance": "RNA用ACGU，DNA用ACGT；均值/中位数按设计显式标记，参考图用全量每组mean，缺值不得补0。",
    "sources": [
      "seqT_sequence_features"
    ]
  },
  "S07": {
    "code": "S07",
    "title": "蛋白质全部20种标准氨基酸组成",
    "target_design": "20标准AA的median点与IQR区间，按组轻微错位；额外other/stop/QC有明确辅助入口。",
    "target_location": "proteome_aa_percentage；genome_cds_translated_aa与transcriptome_orf_translated_aa的翻译代理。",
    "specific_acceptance": "蛋白AA_*_pct为百分数，翻译代理aa_*_freq为比例；IQR不称CI；20AA固定顺序。",
    "sources": [
      "seqP_sequence_features"
    ]
  },
  "S08": {
    "code": "S08",
    "title": "三层序列元素预算的完整分布",
    "target_design": "按当前组学分面的完整元素预算ECDF，元素/比值为局部选择，避免不同分母混同。",
    "target_location": "三个组学element_budget与transcriptome_rna_nmp_element_budget原Core卡。",
    "specific_acceptance": "DNA atoms/base、RNA atoms/nt、protein atoms/residue分别标注；所有家族字段通过总览和选择可达。",
    "sources": [
      "seqP_sequence_features",
      "seqG_sequence_features",
      "seqT_sequence_features"
    ]
  },
  "S09": {
    "code": "S09",
    "title": "碱基组成与启动子外显子背景",
    "target_design": "基因组promoter/exon GC的同轴ECDF，区域用线型；转录组四碱基组成用紧凑4点图或原参考小柱。",
    "target_location": "genome_region_quality的区域分布子视图；transcriptome_rna_base_complexity的组成主视图。",
    "specific_acceptance": "GC百分数与RNA frac比例明确分开；每条曲线全量有效数据；4碱基不强制补齐未定义值。",
    "sources": [
      "seqG_sequence_features",
      "seqT_sequence_features"
    ]
  },
  "S10": {
    "code": "S10",
    "title": "单特征探索的全尾部与分位区间",
    "target_design": "同一字段的完整ECDF与横向Q05/Q25/median/Q75/Q95区间并列；组别同色，常量真实跳跃。",
    "target_location": "overview.selected-feature、basic.distribution、explorer、compare.feature原图位；使用各自当前字段控件。",
    "specific_acceptance": "同一份完整有限值产生两个画面；区间与ECDF的有效n一致；n=0/1和全常量均明确。",
    "sources": [
      "seqP_sequence_features"
    ]
  },
  "S11": {
    "code": "S11",
    "title": "成对特征全量联合密度",
    "target_design": "实际选择x/y的全量hexbin按组分面，计数log色条与原计数tooltip，坐标保留完整尾部。",
    "target_location": "basic.scatter与已有explorer成对探索。",
    "specific_acceptance": "每个有限源记录只入一格；总计与成员身份守恒；x/y切换重建确定性grid并更新signature。",
    "sources": [
      "seqP_sequence_features"
    ]
  },
  "S12": {
    "code": "S12",
    "title": "极值记录在全体序列中的位置",
    "target_design": "全体有限记录的原值排序轮廓，原保存Top/Low成员以金色点高亮，背景不截断。",
    "target_location": "top_low.topLowOption原图位。",
    "specific_acceptance": "原Top/Low成员保持身份与业务排名；显示排序与业务排名分开，不能重新选极值替代。",
    "sources": [
      "seqP_sequence_features",
      "seqP_top_low_entities"
    ]
  },
  "S13": {
    "code": "S13",
    "title": "原策略类别的完整组成",
    "target_design": "每组真实strategy_cluster的紧凑横向堆叠计数条，组规模与组成同时可见。",
    "target_location": "deep.strategyOption原图卡。",
    "specific_acceptance": "类别来自原strategy_cluster，不重聚类；各类别计数和为全部组记录，含unassigned。",
    "sources": [
      "seqP_sequence_features",
      "seqG_sequence_features",
      "seqT_sequence_features"
    ]
  },
  "S14": {
    "code": "S14",
    "title": "带方向信息的完整耦合网络",
    "target_design": "全部已保存Spearman边的有符号弧线网络，节点稳定布局，正蓝负棕，宽度编码abs(rho)。",
    "target_location": "deep.couplingOption原卡。",
    "specific_acceptance": "节点/边完整，边数与保存表一致；无边说明；不新增相关检验或PPI边。",
    "sources": [
      "seqP_analysis_payload"
    ]
  },
  "S15": {
    "code": "S15",
    "title": "样本比较全特征变化与无配对回退",
    "target_design": "全部保存比较的字段×comparison发散矩阵；另一原卡显示真实配对变化，matched_n=0时显示同字段全组ECDF。",
    "target_location": "sample_comparison.sampleDelta与pairedScatter两个原图位，profile严格分开。",
    "specific_acceptance": "同字段显示标准化不改原delta；无配对时标题明确unpaired，不能按行号造配对。",
    "sources": [
      "seqT_differential_features",
      "seqT_sequence_features",
      "seqT_sample_comparison_payload"
    ]
  },
  "S16": {
    "code": "S16",
    "title": "训练拟合与交叉验证证据对照",
    "target_design": "训练与CV保存指标的点连接图，以及带绝对计数的训练混淆矩阵；拟合与验证标签醒目。",
    "target_location": "ml.confusion原卡内组合，原模型概况保留。",
    "specific_acceptance": "只读保存评估，不重训；混淆计数与预测行数一致；CV误差仅保存时绘制。",
    "sources": [
      "seqP_ml_discrimination_payload"
    ]
  },
  "S17": {
    "code": "S17",
    "title": "全部模型特征的重要度秩比较",
    "target_design": "全部模型特征在RF/abs(logistic coefficient)/permutation重要性三个秩轴上的平行秩线；选择少数高亮，所有线保留。",
    "target_location": "ml.mlImportanceOption原卡。",
    "specific_acceptance": "rank方法与tie规则显式，升降序正确；原始三类值在tooltip，不能相加为新重要性。",
    "sources": [
      "seqP_ml_feature_importance"
    ]
  },
  "S18": {
    "code": "S18",
    "title": "ROC与PR完整保存阈值曲线",
    "target_design": "完整保存ROC和PR阈值折线，各图保留自己的基线、正类及数据性质。",
    "target_location": "ml.roc_curve与ml.pr_curve原两卡分别投影。",
    "specific_acceptance": "所有保存阈值点保留，正类和fitted/OOF来源一致；PR基线来自当前保存正类比例。",
    "sources": [
      "seqP_ml_discrimination_payload"
    ]
  },
  "S19": {
    "code": "S19",
    "title": "真实降维方法与全部预测置信度",
    "target_design": "实际保存embedding的全点图，与保存预测置信度ECDF组合；方法名称来自产物。",
    "target_location": "ml.embedding原图卡内部组合。",
    "specific_acceptance": "pca_fallback不得标成UMAP；记录与预测标签身份一致；无confidence时保留坐标并说明。",
    "sources": [
      "seqP_ml_discrimination_payload",
      "seqP_ml_predictions"
    ]
  },
  "S20": {
    "code": "S20",
    "title": "原选12特征的全记录分布小多图",
    "target_design": "原业务选中12特征的ECDF小多图，全部实体参与各字段统计；特征各自原单位。",
    "target_location": "ml.topFeatureDistribution原卡，局部可展开但非逐字段无限内滚动。",
    "specific_acceptance": "12是原选择范围，不是只读12行；当前任务少于12照实，未保存选择不擅自重新排名。",
    "sources": [
      "seqP_ml_discrimination_payload",
      "seqP_sequence_features"
    ]
  },
  "S21": {
    "code": "S21",
    "title": "指定实体的全选特征比较",
    "target_design": "显式选定实体×全部选定特征的参照分位矩阵，原值、单位和reference n可追溯。",
    "target_location": "compare.entityComparison原卡和现有实体/字段输入。",
    "specific_acceptance": "缺实体或歧义先提示；同任务同字段完整参考；原选择以外实体不混入。",
    "sources": [
      "seqP_sequence_features"
    ]
  },
  "S22": {
    "code": "S22",
    "title": "完整差异实体结果池与贡献来源",
    "target_design": "完整保存候选评分池的rank-score轮廓/点图，以及各primary_driver的紧凑横向贡献计数。",
    "target_location": "entities原ResultBlock内、现有DataTable之前，增加一个内部组合画面。",
    "specific_acceptance": "固定参考池1000条仅指保存评分池；未评分输入不被虚构p值；driver计数不冒称独立特征检验。",
    "sources": [
      "seqP_differential_entities"
    ]
  },
  "S23": {
    "code": "S23",
    "title": "完整数值字段的分位图谱 seqP",
    "target_design": "蛋白全部可数值解析保存列的5/25/50/75/95%分位图谱，下方valid/N曲线；状态见S01。",
    "target_location": "proteome catalog原图；Core家族内同构子图谱。",
    "specific_acceptance": "使用全量行，按本字段min/max显示；常量保留约定0并说明；非数值与全空留在审计。",
    "sources": [
      "seqP_sequence_features"
    ]
  },
  "S24": {
    "code": "S24",
    "title": "完整数值字段的分位图谱 seqG",
    "target_design": "基因组全部数值保存列的五分位图谱与有效率曲线，保留区域/编码家族分组。",
    "target_location": "genome catalog原图与Core家族补充。",
    "specific_acceptance": "与S23同规则，但不得把基因组列硬套蛋白字段；字段数由当前产物决定。",
    "sources": [
      "seqG_sequence_features"
    ]
  },
  "S25": {
    "code": "S25",
    "title": "完整数值字段的分位图谱 seqT",
    "target_design": "转录组全部数值保存列的五分位图谱与有效率曲线，RNA/ORF/Full家族可检索。",
    "target_location": "transcriptome catalog原图与Core家族补充。",
    "specific_acceptance": "RNA Full扩展可用才显示具体值；无ORF字段保留未生成原因；元数据不冒充数值分布。",
    "sources": [
      "seqT_sequence_features"
    ]
  },
  "H01": {
    "code": "H01",
    "title": "真实分析总体与工作流证据概览",
    "target_design": "上下文的HVG/non-HVG横向组成、唯一注释基因量/比例和工作流模式摘要构成概览。",
    "target_location": "Research overview的universe、annotation_coverage、context_coverage分别投影，不重复整幅图。",
    "specific_acceptance": "各context H+N=U；注释按当前universe基因去重；不同来源可重叠；模式状态转紧凑条/表。",
    "sources": [
      "Y_hvg_labels",
      "Y_gene_term_membership",
      "Y_modes",
      "Y_summary"
    ]
  },
  "H02": {
    "code": "H02",
    "title": "全部Core字段的真实分析去向",
    "target_design": "按组学分面的Core字段×context离散状态条带，原注册顺序，完整状态图例。",
    "target_location": "Research overview/input_qc的core_disposition与core_omics按职责投影。",
    "specific_acceptance": "当前每context309字段，metadata/descriptive/alias/tested等原final_status保留；别名不是独立检验。",
    "sources": [
      "Y_core_feature_audit"
    ]
  },
  "H03": {
    "code": "H03",
    "title": "全基因均值与原HVG评分",
    "target_design": "全量gene mean-score坐标，log10(1+saved mean)轴，原HVG/非HVG两类颜色，按context分面或选择。",
    "target_location": "Research phase1的hvg_scatter、original_mean_score；重复位置分别承担概览/细节。",
    "specific_acceptance": "保持原mean、score、标签与有限值；无mean定义不反推；所有上下文动态列出。",
    "sources": [
      "Y_hvg_labels"
    ]
  },
  "H04": {
    "code": "H04",
    "title": "HVG排序的完整背景",
    "target_design": "完整保存HVG排序曲线，原HVG成员高亮，显示排名背景和真实选择边界。",
    "target_location": "Research phase1.original_top_hvg；native原top-HVG卡使用同语法的H30投影。",
    "specific_acceptance": "沿用hvg_rank和is_hvg，不设新阈值；全部非HVG背景保留。",
    "sources": [
      "Y_hvg_labels"
    ]
  },
  "H05": {
    "code": "H05",
    "title": "元数据模式 子集和完整变化模式",
    "target_design": "模式可用性紧凑表、全部子集n_cells×n_hvgs散点、保存pattern的紧凑组成，按实际图位拆分。",
    "target_location": "context_patterns.original_pattern_counts/subset_counts及overview.original_workflow。",
    "specific_acceptance": "没有timecourse/trajectory元数据就展示not_applicable；不生成虚构轨迹；pattern全部记录计数守恒。",
    "sources": [
      "Y_modes",
      "Y_subsets",
      "Y_patterns"
    ]
  },
  "H06": {
    "code": "H06",
    "title": "全部原始特征效应跨上下文矩阵",
    "target_design": "按组学分面的完整feature×context原Cliff效应矩阵，零中心蓝棕发散色，所有context共享实际来源色域。",
    "target_location": "context_patterns.context_effects；跨context比较明确不被单context选择器截成一列。",
    "specific_acceptance": "保存效应不重估，含alias行；全run固定对称域，筛选不静默重新缩放；tooltip有q及原状态。",
    "sources": [
      "Y_feature_tests",
      "Y_core_feature_audit"
    ]
  },
  "H07": {
    "code": "H07",
    "title": "全部特征效应与原全局显著性",
    "target_design": "全部原始effect×-log10(q_global)散点，按context分面；强证据按原strong_raw规则，非估计数在辅助栏。",
    "target_location": "group_comparison.feature_volcano。",
    "specific_acceptance": "0q仅显示floor；invalid q不裁剪；有数值但未tested的记录保持状态解释。",
    "sources": [
      "Y_feature_tests"
    ]
  },
  "H08": {
    "code": "H08",
    "title": "全部协变量调整关联及不稳定拟合",
    "target_design": "按原调整model分面的全部beta×-log10(q_global)证据图，context同色，失败/不稳定拟合列辅助摘要。",
    "target_location": "group_comparison.adjusted_forest卡新增证据/CI内部切换，默认本图，CI为H28。",
    "specific_acceptance": "两个模型各自轴域；beta与原Cliff不可相减；estimated/unstable_fit按照源schema。",
    "sources": [
      "Y_adjusted_feature_tests"
    ]
  },
  "H09": {
    "code": "H09",
    "title": "全部匹配敏感性与方向证据",
    "target_design": "raw Cliff×paired_sign_effect散点，旁边完整matched_H_fraction ECDF；两类估计对象明确。",
    "target_location": "group_comparison.matching原图卡。",
    "specific_acceptance": "context_id+feature_key一对一连接，不重新匹配；缺侧记录保持原因；n_pairs不混入fraction轴。",
    "sources": [
      "Y_matching_diagnostics",
      "Y_feature_tests"
    ]
  },
  "H10": {
    "code": "H10",
    "title": "单特征HVG与非HVG完整分布",
    "target_design": "当前选中特征HVG/non-HVG全值ECDF与同轴分位区间并列，引用prepared value及原单位。",
    "target_location": "group_comparison.distribution及feature详情，选择器保留。",
    "specific_acceptance": "先按当前context确定reference与特征，再按复合键join；默认选择规则写明；不能混合多个context。",
    "sources": [
      "Y_feature_values",
      "Y_hvg_labels",
      "Y_feature_tests"
    ]
  },
  "H11": {
    "code": "H11",
    "title": "全部方向基因集的规模和对称性",
    "target_design": "全部方向基因集n_members ECDF与同特征high/low规模散点，缺一侧明确不参与配对图。",
    "target_location": "group_comparison.sets。",
    "specific_acceptance": "保留scope/direction/context，成员和门槛不重算；不把不存在一侧补0。",
    "sources": [
      "Y_gene_sets",
      "Y_gene_set_members"
    ]
  },
  "H12": {
    "code": "H12",
    "title": "基线富集的全部假设与证据轮廓",
    "target_design": "全部baseline ORA的q证据排序轮廓与全term -log10(q) skyline，按实际source/term稳定定位。",
    "target_location": "phase1或downstream的baseline原图位，各section保持原职责。",
    "specific_acceptance": "不重新校正，不只取显著term；固定快照84term/context，未来由数据决定。",
    "sources": [
      "Y_baseline_ora"
    ]
  },
  "H13": {
    "code": "H13",
    "title": "方向子集与HVG内部富集的完整证据范围",
    "target_design": "directional subset、within-HVG及supplementary/joint ORA分开的全q ECDF，非估计数写辅助行。",
    "target_location": "downstream.subset与within_hvg各卡；扩展族在同卡有清楚scope局部入口。",
    "specific_acceptance": "所有保存行都在统计/状态中，有限q才进ECDF；统计背景与校正族分别保留。",
    "sources": [
      "Y_feature_set_ora",
      "Y_within_hvg_ora",
      "Y_supplementary_ora"
    ]
  },
  "H14": {
    "code": "H14",
    "title": "完整连续特征与功能关联空间",
    "target_design": "按GO_BP/GO_CC/GO_MF/KEGG等实际source分面的全效应/q hexbin密度空间，各面板真实测试计数色条。",
    "target_location": "phase2.feature_function原卡，scope使用现有筛选。",
    "specific_acceptance": "有限点全入格；source随实际注释库动态；原effect与q不重算，失败条目保留辅助计数。",
    "sources": [
      "Y_feature_pathway_tests"
    ]
  },
  "H15": {
    "code": "H15",
    "title": "全部特征排序GSEA结果与不可得状态",
    "target_design": "全部有限NES×-log10(q)证据空间，旁边NES/计算状态×context的紧凑计数矩阵。",
    "target_location": "phase2.gsea原卡。",
    "specific_acceptance": "NES不可得不填0；conservative p状态与NES定义分开；不能因p可用便假称NES有效。",
    "sources": [
      "Y_gsea_results"
    ]
  },
  "H16": {
    "code": "H16",
    "title": "完整保存基因排序的GSEA运行曲线",
    "target_design": "完整保存排序的running ES主曲线，下方同rank轴命中刻线，标题明确feature、term、run与背景。",
    "target_location": "ResearchSection现有GSEA详情，不新增通路首页。",
    "specific_acceptance": "完整rank/hits重建ES误差<=1e-8；无保存排序无法绘曲线，不能从预览插值；不重算NES/p。",
    "sources": [
      "Y_ranked_genes",
      "Y_gene_term_membership",
      "Y_gsea_results"
    ]
  },
  "H17": {
    "code": "H17",
    "title": "交互关联的全假设与可估计边界",
    "target_design": "全部可估计interaction beta/q证据图与所有假设状态×context计数矩阵。",
    "target_location": "phase2.interactions原卡。",
    "specific_acceptance": "insufficient_four_cell_groups、rank_deficient、unstable_fit不填0；estimated-only主点与全状态分母对应。",
    "sources": [
      "Y_feature_pathway_interactions"
    ]
  },
  "H18": {
    "code": "H18",
    "title": "功能类别内部的全部原始与调整比较",
    "target_design": "within-function原始Cliff与调整beta的证据图并列或投影到原两卡，各自轴与q族。",
    "target_location": "downstream.within_raw与within_adjusted；不要将同一packet重复展示两族。",
    "specific_acceptance": "原功能成员/背景/标签不变；raw与adjusted估计对象不同。",
    "sources": [
      "Y_within_pathway_tests",
      "Y_within_pathway_adjusted"
    ]
  },
  "H19": {
    "code": "H19",
    "title": "完整技术稳定性与敏感性证据",
    "target_design": "全部技术rerun的Jaccard按保存次序点线、方向一致性ECDF、集合/阈值ECDF、基因频率ECDF四类证据。",
    "target_location": "model_evidence.replication/feature_stability/set_stability/threshold_stability及candidate_frequency相关原图位。",
    "specific_acceptance": "技术重跑不是生物重复；不同run kind分别说明；全部频率记录参与。",
    "sources": [
      "Y_replication_runs",
      "Y_feature_stability",
      "Y_set_stability",
      "Y_threshold_sensitivity",
      "Y_gene_hvg_stability"
    ]
  },
  "H20": {
    "code": "H20",
    "title": "功能与特征的完整重跑敏感性",
    "target_design": "按原q_within_sensitivity_run的通过频率ECDF与全部feature-rerun效应ECDF，技术类型可切换。",
    "target_location": "model_evidence.baseline_stability原卡及现有敏感性区域。",
    "specific_acceptance": "频率分母为该term真实对应rerun数；不是新全局q或后验概率；不创建额外bootstrap。",
    "sources": [
      "Y_baseline_enrichment_stability",
      "Y_feature_sensitivity"
    ]
  },
  "H21": {
    "code": "H21",
    "title": "全部候选基因的优先级 稳定性和证据层级",
    "target_design": "全部候选priority_rank×technical frequency散点，注释标识用形状，context同色；紧凑横向tier组成。",
    "target_location": "downstream.candidate_priority、candidate_tiers，candidate_frequency按当前职责。",
    "specific_acceptance": "保存rank/tier不重排；注释缺失非0频率；同gene不同context可多行。",
    "sources": [
      "Y_candidate_genes"
    ]
  },
  "H22": {
    "code": "H22",
    "title": "候选功能富集与全部证据链接",
    "target_design": "完整候选ORA证据轮廓，以及真实gene–function链接support_type×context的紧凑组成。",
    "target_location": "downstream.candidate_ora原卡及已有候选功能链接入口。",
    "specific_acceptance": "链接计数不是独立基因数；无PPI数据保留原因，不虚构网络。",
    "sources": [
      "Y_candidate_ora",
      "Y_gene_pathway_links",
      "Y_network_status"
    ]
  },
  "H23": {
    "code": "H23",
    "title": "指定真实候选基因的全部Core档案",
    "target_design": "明确选定gene的全309原始Core字段按组学条带档案，非HVG同context参考分位；灰格保留不可用原因。",
    "target_location": "genes详情内现有geneProfile位置，ResearchSection的H23入口。",
    "specific_acceptance": "当前context/gene唯一；全Core包括metadata/descriptive/alias，不只48项；分位不是基因显著性。",
    "sources": [
      "Y_candidate_genes",
      "Y_core_feature_audit",
      "Y_feature_values",
      "Y_hvg_labels"
    ]
  },
  "H24": {
    "code": "H24",
    "title": "历史预测分支的完整信号 残差和类别",
    "target_design": "历史已保存expected×observed全点密度，excess residual ECDF与紧凑原类别组成三证据。",
    "target_location": "仅legacy有模型的phase2，分别投影expected_observed/residuals/classes三个原图位。",
    "specific_acceptance": "不在model_policy=removed任务造预测；训练拟合不叫验证；类别原定义。",
    "sources": [
      "A_hvg_stoich_scores"
    ]
  },
  "H25": {
    "code": "H25",
    "title": "历史分支完整模型证据与富集",
    "target_design": "历史模型所有特征关联点线、selection_frequency×importance散点、全部模型R²点线、ORA/GSEA分族证据。",
    "target_location": "legacy model_evidence及downstream的original_*图位分别投影。",
    "specific_acceptance": "8特征/4模型仅参考快照；历史族不与Research混q；没有原GSEA不填造。",
    "sources": [
      "A_feature_associations_table",
      "A_bootstrap",
      "A_model_comparison_table",
      "A_enrichment_ora",
      "A_gsea"
    ]
  },
  "H26": {
    "code": "H26",
    "title": "完整检出率 脱落率及HVG评分分布",
    "target_design": "dropout、detected fraction、HVG score的三个独立原尺度ECDF，按context颜色。",
    "target_location": "phase1.original_dropout与hvg_histogram分别投影到原卡。",
    "specific_acceptance": "比例与百分比按源schema，不默认乘100；零边界和1边界完整；重叠context不合为独立基因。",
    "sources": [
      "Y_hvg_labels"
    ]
  },
  "H27": {
    "code": "H27",
    "title": "完整Core缺失与基因准入原因",
    "target_design": "全Core的组内missing/n缺失比例ECDF，以及全部gene eligibility reason×context计数矩阵。",
    "target_location": "input_qc的eligibility/core_missingness；mapping_coverage按原映射职责。",
    "specific_acceptance": "n=0不除0；不适用非测量缺失；所有准入原因可见，来源分母不同。",
    "sources": [
      "Y_core_feature_audit",
      "Y_gene_eligibility"
    ]
  },
  "H28": {
    "code": "H28",
    "title": "全部非模型关联效应的原始置信区间",
    "target_design": "原始Cliff CI、每个调整model beta与ln(OR) CI分别在独立面板按效应排序绘制全量区间密度。",
    "target_location": "group_comparison.feature_forest主图及adjusted_forest卡的CI子视图。",
    "specific_acceptance": "取ln只针对声明为OR的正区间；原Cliff CI不变；估计与上下界对齐，失败仍可审计。",
    "sources": [
      "Y_feature_tests",
      "Y_adjusted_feature_tests"
    ]
  },
  "H29": {
    "code": "H29",
    "title": "原生HVG非模型组间比较的完整结果",
    "target_design": "完整原生非模型比较：raw效应/q、调整失败原因或有效调整证据、family tested×significant、全部组分位范围ECDF。",
    "target_location": "HvgGroupComparisonPanel五个原图位，见正文五图位表；Research历史original_*按profile同构投影。",
    "specific_acceptance": "raw/adjusted/family/quantile各自独立分母；248全failed快照只显示失败证据，不造系数。",
    "sources": [
      "A_hvg_nonhvg_feature_comparison",
      "A_hvg_nonhvg_adjusted_comparison",
      "A_hvg_nonhvg_family_summary",
      "A_hvg_nonhvg_distribution_quantiles"
    ]
  },
  "H30": {
    "code": "H30",
    "title": "原生HVG基线的全部基因分布",
    "target_design": "原生全部gene mean-score图、完整score或rank背景、dropout ECDF，按原三个phase1图位分别投影。",
    "target_location": "HvgCaseView native phase1Scatter、topHvgOption、dropoutScatter。",
    "specific_acceptance": "原22017基因/3000HVG仅固定快照；pct_cells_detected范围先核对再计算1-pct。",
    "sources": [
      "A_hvg_baseline"
    ]
  },
  "H31": {
    "code": "H31",
    "title": "原生HVG映射与完整Core审计",
    "target_design": "原生全Core audit状态×组学的紧凑横向组成/状态矩阵，旁边完整missing rate ECDF。",
    "target_location": "native input_qc映射卡；mapping质量与Core审计分开局部视图。",
    "specific_acceptance": "309原字段及缺失原因保留；gene映射率用实际映射表，不能用Core tested比例替代。",
    "sources": [
      "A_hvg_nonhvg_feature_audit"
    ]
  },
  "H32": {
    "code": "H32",
    "title": "原生候选结果的完整得分与背景",
    "target_design": "全部真实candidate excess×score密度空间，以及完整已评分gene的保存score背景轮廓。",
    "target_location": "native/legacy downstream.candidateBubble或original_candidate_bubble。",
    "specific_acceptance": "候选表与全基因scores按gene身份连接；score原定义，不新训练、不新候选选择。",
    "sources": [
      "A_candidate_score_components_table",
      "A_hvg_stoich_scores"
    ]
  }
}
