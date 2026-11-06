# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.
O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- Config flow completo: identificador do site, InfluxDB (URL, organização, bucket, token) e URL de push do Uptime Kuma, com escrita de teste no InfluxDB antes de salvar.
- Options flow: intervalo de coleta, URL de limites remotos, entidades ignoradas, entidades Zigbee, entidade de backup e opção de enviar `down` ao Kuma quando crítico.
- Reconfigure flow para trocar URL e token sem remover a integração.
- Envio a cada ciclo ao InfluxDB (line protocol, um POST por ciclo) e heartbeat ao Uptime Kuma, independentes entre si e sem afetar o HA em caso de falha.
- Coordenador com cálculo do nível geral (pior nível entre as checagens).
- Checagens: `integrations`, `unavailable_entities`, `system` (`disk_use`, `memory_use`, `load_1m`, `host_uptime`, `ha_uptime`), `system_log`, `recorder`, `updates`, `backup` e `zigbee`, cada uma isolada das demais.
- Limites padrão embutidos para todas as checagens.
- Entidades com IDs fixos: `sensor.mmh_health`, um `sensor.mmh_<checagem>` por medição, `binary_sensor.mmh_problema` e `binary_sensor.mmh_envio_central`.
- Estrutura inicial da integração `mmh_monitor` (manifest, config flow mínimo com validação do identificador do site, instância única).
- Workflows de CI: hassfest, validação HACS e pytest, com actions fixadas por hash de commit.
- Dependabot para manter as actions do CI atualizadas.
- Seção de segurança e privacidade no README.
