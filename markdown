Issues found in 9 inputs. Find details below.

[docs/analysis/EMBEDDING_ADAPTERS.md]:
[403] https://platform.openai.com/docs/guides/embeddings (at 514:32) | Rejected status code: 403 Forbidden

[docs/analysis/OTEL_AND_DEVICE_DISCOVERY.md]:
[ERROR] http://localhost:16686/ (at 366:11) | Connection refused - server may be down or port blocked
[ERROR] http://localhost:3000/ (at 365:12) | Connection refused - server may be down or port blocked
[ERROR] http://localhost:5601/ (at 368:11) | Connection refused - server may be down or port blocked
[ERROR] http://localhost:9090/ (at 367:15) | Connection refused - server may be down or port blocked

[docs/guides/operational-modes.md]:
[406] http://localhost:8680/mcp (at 325:39) | Rejected status code: 406 Not Acceptable
[406] http://localhost:8683/mcp (at 324:37) | Rejected status code: 406 Not Acceptable

[docs/monitoring/ALERTING_SETUP.md]:
[ERROR] http://localhost:9093/ (at 474:32) | Connection refused - server may be down or port blocked

[docs/monitoring/GRAFANA_DASHBOARDS.md]:
[ERROR] http://localhost:3000/ (at 501:26) | Error (cached)
[ERROR] http://localhost:3000/ (at 70:26) | Error (cached)

[docs/reference/service-dependencies.md]:
[406] http://localhost:8676/mcp (at 209:12) | Rejected status code: 406 Not Acceptable
[406] http://localhost:8678/mcp (at 197:12) | Rejected status code: 406 Not Acceptable
[406] http://localhost:8682/mcp (at 203:12) | Rejected status code: 406 Not Acceptable

[docs/runbooks/INCIDENT_RESPONSE.md]:
[ERROR] http://alertmanager:9093/ (at 1370:21) | Connection failed. Check network connectivity and firewall settings
[ERROR] http://grafana:3000/dashboards (at 1368:30) | Connection failed. Check network connectivity and firewall settings
[ERROR] http://grafana:3000/explore (at 1371:18) | Connection failed. Check network connectivity and firewall settings
[ERROR] http://prometheus:9090/alerts (at 1369:26) | Connection failed. Check network connectivity and firewall settings

[docs/runbooks/MAINTENANCE.md]:
[ERROR] http://grafana:3000/dashboards (at 901:30) | Connection failed. Check network connectivity and firewall settings
[404] https://pagerduty.com/schedules (at 902:25) | Rejected status code: 404 Not Found | Followed 1 redirect. Redirects: https://pagerduty.com/schedules --[301]--> https://www.pagerduty.com/schedules

[docs/runbooks/TROUBLESHOOTING.md]:
[ERROR] http://grafana:3000/dashboards (at 992:30) | Connection failed. Check network connectivity and firewall settings

🔍 193 Total (in 5s 450ms) 🔗 134 Unique ✅ 151 OK 🚫 20 Errors 👻 22 Excluded 🔀 9 Redirects
