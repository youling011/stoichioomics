# 独立联调材料

这些脚本只供专用 Linux 验证环境使用。`fixture.py` 会向空的临时数据库写入合成数据，要求 `STOICH_VALIDATION_ONLY=1` 且数据库名以 `test_stoich_deploy_` 开头；不要指向业务库。迁移、创建数据库和启动服务由独立验证环境显式管理。

`smoke.py` 验证真实 HTTPS / Nginx / uWSGI / Django / PostgreSQL 链路。需提供测试证书 CA、域名解析和合成数据。默认只做读取检查；`--writes` 显式启用小型序列上传分析与导出任务。这些写入只允许发生在专用测试环境。示例：

```bash
python -m deploy.validation.fixture
python -m deploy.validation.smoke --base https://platform.test --ca /test/cert.pem --report /test/smoke.json --writes
```

脚本对直接 Django 响应与 Nginx/uWSGI 响应进行字节级比较。它验证合成样本的任务执行，无法代替真实组学数据全量验收、并发压力、进程崩溃恢复、正式域名证书和 systemd 开机管理的检查。
