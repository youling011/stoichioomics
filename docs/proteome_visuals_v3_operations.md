# Proteome 可视化 v3 运行与维护

本版覆盖 Basic B01–B15、Deep D01–D16，共 31 个图位；B10 引用 D02，独立定义 30 个。统计以完整 Core 主体为默认，Full 具有独立主体和来源版本。既有导航、其他组学与旧接口继续使用原有契约。

## 预计算范围

按用户 2026-10-20 的最新要求，仅对常见标准物种清单预计算。项目保存的原始清单位于 `data/model_organism_release_hardening/S0_freeze_baseline_20260731_031917/config_snapshot/六类群白名单_模式生物清单.csv`，693 行、691 个唯一物种。核对后的执行清单为 `data/proteome_visuals/common_species_20261020.txt`，来源及 SHA-256 见同目录 manifest。当前 691 个物种均已完成 Core/Full 产物和审计。不要例行运行全平台注册物种预计算。

在项目根目录运行：

```powershell
& '.\.venv\Scripts\python.exe' manage.py materialize_proteome_visuals --species-file data/proteome_visuals/common_species_20261020.txt --scope core --with-full --workers 2 --resume --publish
& '.\.venv\Scripts\python.exe' manage.py audit_proteome_visuals --species-file data/proteome_visuals/common_species_20261020.txt --scope core --report-json runtime/proteome_visuals_v3/common_core_audit.json --report-csv runtime/proteome_visuals_v3/common_core_audit.csv --fail-on-error --publish
& '.\.venv\Scripts\python.exe' manage.py audit_proteome_visuals --species-file data/proteome_visuals/common_species_20261020.txt --scope full --report-json runtime/proteome_visuals_v3/common_full_audit.json --report-csv runtime/proteome_visuals_v3/common_full_audit.csv --fail-on-error --publish
```

`--resume` 同时核对方法、实现哈希、文件签名和源文件内容 SHA-256。`--force` 写新版本。原始 CSV、Parquet 和生产数据库记录保持不变。Full 可用性以实际文件为准，不能用注册行数 0 排除。超过 100,000 行的物种独占一批；原生数值线程在这些显式 CLI 入口限制为 1。

## 其他物种首次访问

页面发现产物缺失或过期时，调用 `POST /api/stoichdb/species/{species_id}/proteome/visualizations/ensure/`，只接受 `scope`。系统建立去重任务，启动真正的 CLI 消费进程并返回 queued/running；页面轮询任务，审计和发布完成后自动展示结果。已有版本直接复用。

消费者使用无可见窗口的独立进程；空闲 45 秒自动退出并移除心跳。当前实现不需要额外常驻服务。比较集合中缺失的物种指纹也会请求准备。切换页面取消旧请求和轮询，计算产物可以完成并被以后访问复用。

管理员手工排空任务：

```powershell
& '.\.venv\Scripts\python.exe' manage.py materialize_proteome_visuals --consume-requests --once
```

显式常驻消费者仅在运维需要时运行 `--consume-requests --poll-seconds 5`；使用结束需退出。失败任务保留原因，页面提供重试。死进程留下的任务和声明文件可恢复，活动任务不会被抢占。

## 版本、导出与数据更新

默认产物根目录为 `runtime/proteome_visuals_v3`，含独立版本目录、已审核发布指针、旧版本索引、请求文件和运行日志。文件系统目录使用短哈希以兼容 Windows 路径长度；完整身份保留于 manifest。

页面缓存按物种、scope、release、方法、源哈希、产物版本隔离；自选坐标还有 variant_id，比较集合还有 cohort_hash。结构概览覆盖所有排序记录，精确窗口支持任意起点与 100/250/1000 条记录。主排名要求完整评分组件，部分证据单列。

导出使用服务端原值和计数；CSV/TSV 格式参数名为 `file_format`，避免 DRF 将 `format=csv` 当作渲染器协商而返回 404。自选坐标导出携带 variant_id。PNG 为 4 倍像素，SVG 为真实矢量；精确结构窗口另外提供包含实际 ID 和 7 项原值的 JSON。

源文件正常更新后文件签名使页面显示过期并触发重建；主动替换数据、算法升级或保留文件时间戳的特殊变更，应运行上述内容哈希校验和重建命令。更新不通过覆盖旧产物实现。

## 测试与回退

```powershell
& '.\.venv\Scripts\python.exe' manage.py test backend.apps.stoichdb.tests.test_proteome_viz_statistics backend.apps.stoichdb.tests.test_proteome_viz_sources backend.apps.stoichdb.tests.test_proteome_viz_contracts backend.apps.stoichdb.tests.test_proteome_viz_api --settings=backend.config.settings_proteome_viz_test --noinput
Set-Location frontend
npm.cmd run test:proteome
npm.cmd run test:proteome:e2e
```

后端测试使用独立 PostgreSQL 测试库和临时目录。浏览器测试连接专用只读验证后端，默认前端 5177；配置文件为 `playwright.proteome.config.mjs`，复用本机 Chrome，不会迁移或清空生产库。环境变量 `PROTEOME_FRONTEND_URL`、`PROTEOME_CHROME_PATH`、`PROTEOME_PLAYWRIGHT_REPORT` 可覆盖验证地址、浏览器与报告路径。

快速回退：设置 `STOICH_PROTEOME_VIZ_V3_ENABLED=0` 并按现有方式重启后端，前端读到禁用标志后恢复旧 Proteome 加载分支。源码备份和 SHA 清单位于 `runtime/proteome_viz_implementation_backup_20261020`。需要源码回退时依据清单逐文件恢复，保留后续其他任务修改和原始数据。
