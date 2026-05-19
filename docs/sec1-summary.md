# Sec.1 基础设施搭建小结（M1 阶段）

> 对应里程碑：`design.md §7 — M1 docker-compose 起 ES + Mongo`
> 完成日期：2026-05-19

## 1. 交付物清单

| 文件 / 目录              | 作用                                                   |
|--------------------------|------------------------------------------------------|
| `docker-compose.yml`     | Elasticsearch + MongoDB + Tika 一键编排                |
| `.env.example`           | 版本号、端口、堆内存、Mongo 账号的可调参数模板             |
| `.gitignore`             | 屏蔽 `.venv/`、`data/snapshots/`、缓存与日志              |
| `data/snapshots/`        | gzip 网页快照存放目录（M2 起写入）                       |
| `data/graph/`            | PageRank 邻接表 / 中间结果（M5 起写入）                  |

## 2. 服务清单

### 2.1 Elasticsearch 8.13.4

- 单节点（`discovery.type=single-node`），开发模式
- **关闭** xpack security / SSL，免去证书与登录配置
- 堆内存默认 `-Xms1g -Xmx1g`，可通过 `.env` 覆盖
- 关闭 `ingest.geoip.downloader`，避免首启动联外网
- 启用 `bootstrap.memory_lock`，防止 swap
- 数据卷：`es_data`、`es_logs`
- 健康检查：轮询 `/_cluster/health`，状态非 red 即通过
- 端口：`9200`

### 2.2 MongoDB 6.0

- 启用 root 账号（默认 `isr` / `isr_dev_pw`），生产环境务必改 `.env`
- 默认库：`isr`
- 数据卷：`mongo_data`、`mongo_config`
- 健康检查：`mongosh --eval "db.adminCommand('ping').ok"`
- 端口：`27017`

### 2.3 Apache Tika 2.9.2.1-full

- 用作 `parser/doc_parser.py` 的后端（M3 文档解析）
- `full` 镜像自带 PDF / OCR / Office 解析器
- 端口：`9998`

## 3. 启动与验证

```bash
# 1. 准备环境变量
cp .env.example .env

# 2. 启动
docker compose up -d

# 3. 查看健康状态
docker compose ps

# 4. 单点验证
curl -s http://localhost:9200 | jq .version.number       # ES
curl -s http://localhost:9200/_cluster/health | jq .     # 集群健康
docker exec isr-mongo mongosh -u isr -p isr_dev_pw \
  --authenticationDatabase admin --eval 'db.runCommand({ ping: 1 })'
curl -s http://localhost:9998/tika                       # Tika
```

预期输出：
- ES `version.number` = `8.13.4`，`cluster.health.status` = `green` 或 `yellow`
- Mongo `{ ok: 1 }`
- Tika 返回欢迎语 `This is Tika Server ...`

## 4. 关键设计权衡

| 决策                        | 理由                                                       |
|---------------------------|----------------------------------------------------------|
| ES 关 xpack security      | 开发期减少证书 / 用户管理负担；外网不暴露端口即可                      |
| Mongo 启 root + 密码       | 与未来 docker-compose 多服务复用对齐；生产改强密码即可                |
| Tika 独立 server 而非进程内 | 解析崩溃不影响主程序；与 Python `tika-python` 客户端配合更稳            |
| 选 8.13.4 / 6.0            | 与生产 LTS 对齐，避免 9.x / 7.x 行为差异                          |
| 不引入 Kibana             | 课程作业无需可视化运维；如需调试，curl + `_cat/indices` 已够        |
| 不引入 ik 分词插件          | 留待 `indexer/` 索引构建阶段决定（design.md §3.3）                  |

## 5. 已知风险与缓解

- **WSL2 内存抖动**：ES `memory_lock` 在 WSL 偶发失败；如启动报 lock 错误，调低 `ES_JAVA_OPTS` 或在 `wslconfig` 提升 memory 配额
- **Mongo 默认密码**：`isr_dev_pw` 仅供本地开发；提交代码时确认 `.env` 已被 `.gitignore` 屏蔽
- **Tika full 镜像体积大**（~1.4 GB）：M3 真正调用前可临时 `docker compose stop tika`

## 6. 下一步（衔接 M2）

- [ ] 初始化 `crawler/` Scrapy 项目骨架（`scrapy startproject isr_crawler`）
- [ ] 定义统一 Item schema（对齐 `design.md §3.1`）
- [ ] 实现 `pipelines.py`：清洗 → Mongo 写入 → gzip 快照落盘
- [ ] 跑通 Fandom spider 单 wiki 1 万条
