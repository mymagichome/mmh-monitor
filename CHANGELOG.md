# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.
O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

## [0.1.2] - 2026-11-06

### Corrigido
- Falso crítico logo após reiniciar o HA: as checagens `zigbee`, `unavailable_entities` e `integrations` dependem de outras integrações terem carregado. Agora elas ficam como "não monitorado" até 5 minutos depois de o HA terminar de iniciar, e uma coleta completa roda assim que esse período acaba.

## [0.1.1] - 2026-11-06

### Corrigido
- `backup`: passa a considerar todos os backups conhecidos pelo HA (agendamento nativo, automações com `hassio.backup_full` e backups manuais), e não só os do agendamento automático nativo. A lista é lida no máximo a cada 30 minutos.

### Alterado
- `backup`: limites padrão ajustados ao padrão MMH (backup a cada 15 dias, no máximo 30): atenção com 16 dias (384 h) e crítico com 30 dias (720 h).
- `backup`: fica crítico se a última tentativa do backup automático nativo falhou.

## [0.1.0] - 2026-11-06

Primeira versão, para o piloto.

### Adicionado
- Config flow completo: identificador do site, InfluxDB (URL, organização, bucket, token) e URL de push do Uptime Kuma, com escrita de teste no InfluxDB antes de salvar.
- Options flow: intervalo de coleta, URL de limites remotos, entidades ignoradas, entidades Zigbee, entidade de backup e opção de enviar `down` ao Kuma quando crítico.
- Reconfigure flow para trocar URL e token sem remover a integração.
- Envio a cada ciclo ao InfluxDB (line protocol, um POST por ciclo) e heartbeat ao Uptime Kuma, independentes entre si e sem afetar o HA em caso de falha.
- Coordenador com cálculo do nível geral (pior nível entre as checagens).
- Checagens: `integrations`, `unavailable_entities`, `system` (`disk_use`, `memory_use`, `load_1m`, `host_uptime`, `ha_uptime`), `system_log`, `recorder`, `updates`, `backup` e `zigbee`, cada uma isolada das demais.
- Limites padrão embutidos para todas as checagens.
- Limites remotos: JSON em `thresholds_url` buscado a cada 6 horas, validado e mesclado campo a campo (`sites.<slug>` > `checks` > padrão), com cache local para reinícios e quedas de rede.
- Reparos: checagem crítica abre um aviso em Configurações → Reparos, removido quando volta a OK ou atenção.
- Diagnóstico com configuração (token, URL do Kuma e URL dos limites redigidos), limites vigentes, último resultado e status dos envios.
- Entidades com IDs fixos: `sensor.mmh_health`, um `sensor.mmh_<checagem>` por medição, `binary_sensor.mmh_problema` e `binary_sensor.mmh_envio_central`.
- Estrutura inicial da integração `mmh_monitor` (manifest, config flow mínimo com validação do identificador do site, instância única).
- Workflows de CI: hassfest, validação HACS e pytest, com actions fixadas por hash de commit.
- Dependabot para manter as actions do CI atualizadas.
- README em pt-BR: instalação, configuração, entidades, checagens, limites, esquema de dados, diagnóstico e segurança.
- Guia do servidor central (`docs/central.md`), dashboard do Grafana (`docs/grafana/`) e exemplo de limites (`docs/thresholds.example.json`).

[Não lançado]: https://github.com/mymagichome/mmh-monitor/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/mymagichome/mmh-monitor/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/mymagichome/mmh-monitor/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/mymagichome/mmh-monitor/releases/tag/v0.1.0
