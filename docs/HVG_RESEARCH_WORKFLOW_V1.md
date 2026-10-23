# HVG化学计量与功能关联研究使用、方法与运行说明

适用主体：`G:\stoichioomics\项目平台数据\stoich_platform_postgres_open_search_v6_2_perf_fix\proj`。版本 `hvg_research_v1`，更新2026-10-16。

## 入口与结果

正常启动原平台后，“新建任务”的 Run objective 选择“HVG化学计量与功能关联完整研究”。上传真实表达矩阵及可选metadata，确认物种、矩阵语义、官方HVG flavor、TopN及批次字段。counts与log输入不可混用；缺少原始counts时不假定raw等于counts，不静默换算法。任务详情可预检、执行、取消、查看阶段、恢复、设置保留期限。

已注册完整公开案例：`/hvg/GSE123818_complete`。原历史案例 `/hvg/hvg_prod_arath_gse123818_v1` 保留旧视图。研究页含研究概览、全Core特征、方向基因集、富集对照、特征与功能、功能内部比较、候选与单基因、稳健性、完整下载；可查看独立global旧模型。

只有完整计算的统计表决定p/q。页面图仅显示当前筛选窗口，不改变检验家族。分页可遍历全表，下载包含完整表、成员、背景、映射、方法、排序、置换与图源数据。普通CSV保持基因ID原值；“安全表格导出”单独处理公式注入。UTF-8非ASCII ID保留。

## 配置

实际配置校验与默认值以 `backend/analysis_engine/hvg_research/config.py` 为准；机器可读字段schema：`shared/schemas/hvg_research_config_v1.json`。该JSON schema用于字段类型与结构说明，跨字段范围、不变量和路径约束由Python校验器执行。未知参数拒绝；配置分段深合并，不能浅覆盖丢失其他参数。

- 完整示例 `configs/examples/hvg_research_GSE123818_complete.yaml`：500次完整组bootstrap、每term1000次真实GSEA置换、10次80%技术细胞重采样。
- `hvg_research_smoke.yaml`：800真实细胞、降低重复数的工程冒烟；研究状态为partial并明确精度限制，不用于正式生物学结论。
- `hvg_research_source_missing.yaml`：真实counts故意指定缺少注册数据的物种，仅测试缺源状态，不作为生物学实例。
- `hvg_research_cancel_resume.yaml`：取消与同run恢复验收fixture。

`core.omics`决定请求的组学源，注册表中的全部合法Core仍逐字段对账。该实例注册309，248个非重复合格字段用于方向集合；原始单字段统计保留重复别名并标记，另有描述/排除/缺源/质量失败原因。新合法Core不会因309常数被忽略；未审查语义字段保留描述，不自动纳入推断。Full字段不自动混入Core。

`gene_sets`默认以同特征适用non-HVG的Q20/Q80为参考，低/高两方向都计算，先固定阈值再形成HVG子集；不能先挑显著特征后缩小FDR范围。binary按0/1，不用连续分位数替代。

`enrichment.annotation_release_id`为空时要求唯一active release；也可显式冻结。GO_BP/MF/CC、KEGG_pathway/module分开标记。当前源无GO证据码/DAG，记录不可用，不伪造证据码或祖先传播。

## 方法与解释

主HVG由官方Scanpy直接给出，H/N在Core映射之前冻结。各feature使用适用且非缺失背景Uf，功能检验再与指定注释源交集。原始HVG富集可独立于Core/旧模型执行；特征子集对全背景富集F4、HVG内部条件富集F5以及同背景重算baseline分别保留。

按单位先规范，再保留原值、准备值、模型值三层。百分比转fraction；计数/长度合理log1p，正比值log；完整组成产生CLR单项与ILR联合坐标。模型共享冻结U的按列IQR尺度，IQR退化时回退SD；从不对H/N分别标准化。MWU/Cliff用秩，避免大单位直接支配；相关簇/特征家族对候选证据去重。

保留原始差异、置信区间、表达/检测及长度校正、匹配平衡与成员、连续特征—功能关系、真实特征rank GSEA、功能内H/N差异、独立feature×term交互。GLM秩亏、分离、样本不足或不稳定时给状态和空p。功能内校正及交互当前均要求功能内外H/N四组达到最小数，偏保守并可能降低覆盖；原始功能内比较独立保留。

BH在所有预声明context和相应完整家族收集后统一计算，BY单列。校正模型、补充集合、敏感性分别命名家族。GSEA保存真实rank、leading edge、置换null数组；无同号null使NES不可估计时显式标记，p给保守上界，不能当显著结果。enrichment_comparison是对齐展示表，包含重复对照行，其显著行数不等于独立发现数。

候选池仅官方主HVG，以强差异门槛、方向集合、去冗余家族、真实功能overlap及技术稳定性整合。A/B为进一步研究的优先级，不是基因层面p值；无注释强特征候选保留。序列特征不等于实测资源消耗；技术重采样/文库敏感性不等于供体或外部数据复现。

## API

统一前缀 `/api/hvg/<case_or_job>/research/`。已注册public case可读取；真实job需要原有 `X-Job-Token`，先校验任务所有权再读取run。所有GET可带 `analysis_run_id`；多context详情必须明确 `context_id`。

|接口|内容|
|---|---|
|summary、runs、contexts|状态、覆盖、运行版本、情境|
|features、core-audit|完整特征检验/审计分页|
|features/<key>|分布、校正、匹配、集合、稳定性|
|gene-sets、gene-sets/<id>|定义与真实成员|
|enrichment?kind=baseline/matched_baseline/subset/within_hvg/supplementary_ora|分别的检验家族|
|enrichment-comparison|同背景对照表|
|feature-pathways?method=distribution/gsea/gsea_runs/interaction/leading_edge/ranked_genes|功能关系、适用性和真实排序|
|within-pathways、candidates、stability|功能内比较、候选、稳健性|
|genes/<gene_id>|全部Core值、映射、集合、功能、稳定性等基因证据|
|phenomena、plots/<kind>、optional-model|结构化观察、图源数据、独立旧模型|
|table/<catalog_key>|catalog中完整逻辑表；非任意文件读取|
|artifacts、download/<artifact_id>、safe-export/<table>|清单、校验和下载、安全表格导出|
|POST retention、resume|仅已授权job的保留/归档、未完成run恢复|

分页page≥1、page_size≤200，支持白名单sort/order、feature/term/source/direction/query/q/context等筛选。详情中的基因q均属于关联特征/集合/功能层次，不能另解为单基因显著性。

## CLI、验证和环境

在项目根目录使用项目venv，不升级原依赖：

```powershell
& .\.venv\Scripts\python.exe -B scripts/audit_hvg_research_environment.py --help
& .\.venv\Scripts\python.exe -B scripts/run_full_analysis_pipeline.py --config configs/examples/hvg_research_GSE123818_complete.yaml
& .\.venv\Scripts\python.exe -B scripts/validate_hvg_research_run.py --run-dir '<实际run绝对路径>' --report '<核验JSON绝对路径>'
& .\.venv\Scripts\python.exe -B manage.py check
& .\.venv\Scripts\python.exe -B manage.py test backend.analysis_engine.hvg_research.tests backend.analysis_engine.phase2.tests.test_group_comparison backend.analysis_engine.phase1.tests backend.apps.jobs.tests.test_hvg_research_workflow backend.apps.jobs.tests.test_autoconfig_h5ad_semantics backend.input_adapter.tests.test_merge_metadata --settings=backend.config.settings_hvg_test --noinput
# 在frontend目录运行下一条构建命令
& 'D:\python\node.js\node.exe' node_modules/vite/bin/vite.js build
```

Vite构建须在frontend工作目录调用 `node node_modules/vite/bin/vite.js build`。准确已执行命令另见最终验收记录。测试设置强制独立PostgreSQL测试库，不能替换为生产settings运行建库测试。关键依赖锁在 `requirements-hvg-research-lock.txt`。本次不新增业务表迁移。

## 运行、恢复、保留和回退

当前`.env`设置 `HVG_RESEARCH_ENABLED=1`；Python默认False。正常启动或重启原平台服务后加载。关闭设置仅阻止创建新研究运行，已有结果保留可读。最终交付不常驻启动临时服务。

每次运行位于job目录 `hvg_functional_comparison/runs/<analysis_run_id>`，完整后才发布active_run。DB短事务claim与OS锁阻止重复执行；独立worker默认1，BLAS线程固定1。取消检查、进程树终止和主进程死亡监测防止遗留worker。既有在进程线程执行器不具备跨机器队列能力。

未完成run可恢复，但代码/配置/输入/注册表/来源hash改变则拒绝复用，需新run。完成run不可覆盖。案例report_r1明确标注report_only_revision及parent，沿用已验证科学表，新增结构化现象与导出，原378文件hash复验不变。

成功研究job默认保留30天，metadata的retain_until/archived实际进入清理判断；可在任务页延长或归档。运行/取消中、恢复、导出及锁占用任务不清理。普通旧任务仍按原TTL。生产研究长期保留需显式归档或下载完整包。

回退先关新任务开关，停止/取消并保存本次研究run；按修改清单恢复原文件及旧frontend/dist，并仅撤销清单内新增源码。基线备份 `F:\codex工作目录\gpt优化方案\项目收尾及相关优化\hvg模块平台进一步优化修改\平台实施备份_20261015`。必须依据baseline_file_manifest判定原有文件，不能把备份目录所有文件盲目覆盖（多次编辑也可能备份新增文件）。保留所有用户输入、研究run和原数据库；无需回退生产注释表。恢复后重建/重启并烟测旧案例、模型和下载。

预检research_workload_budget输出输入cells/genes（H5AD以backed只读后关闭）、所有Core审计数、请求特征上界、源term、context、方向、F×T×C与置换工作量上界；该估算在映射/QC/term规模过滤前，不能当最终结果数或耗时承诺。不会按预算静默截断分析。
