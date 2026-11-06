# MMH Monitor

[![Validate](https://github.com/mymagichome/mmh-monitor/actions/workflows/validate.yml/badge.svg)](https://github.com/mymagichome/mmh-monitor/actions/workflows/validate.yml)
[![Tests](https://github.com/mymagichome/mmh-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/mymagichome/mmh-monitor/actions/workflows/tests.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

Integração do Home Assistant que monitora a saúde de cada instalação de cliente da **My Magic Home (MMH)**.

A cada ciclo (padrão: 5 minutos) ela:

1. roda um conjunto de checagens (integrações com falha, entidades indisponíveis, disco, memória, banco de dados, backup, Zigbee…);
2. classifica cada uma e o site como um todo em **ok**, **atenção** ou **crítico**;
3. envia todas as medições — inclusive as normais, para análise de tendência — a um **InfluxDB** central;
4. envia um heartbeat ao **Uptime Kuma**, que avisa quando o site para de reportar.

A integração **só lê e reporta**. Ela nunca altera nada no Home Assistant do cliente.

```
HA do cliente ──(HTTPS, token só de escrita)──► InfluxDB central ──► Grafana / alertas / relatórios
      └────────(heartbeat)────────────────────► Uptime Kuma
```

O servidor central (InfluxDB, Grafana, Cloudflare Tunnel) está descrito em [docs/central.md](docs/central.md).

---

## Requisitos

- Home Assistant **2026.3.4** ou mais recente.
- HACS instalado.
- InfluxDB 2.x acessível pelo HA, com um bucket e um **token somente de escrita** para o site.
- (Opcional) Um monitor do tipo **Push** no Uptime Kuma para o site.

## Instalação (HACS)

1. No HACS, abra o menu **⋮ → Repositórios personalizados**.
2. Adicione `https://github.com/mymagichome/mmh-monitor` com a categoria **Integração**.
3. Procure **MMH Monitor**, clique em **Baixar** e reinicie o Home Assistant.
4. Em **Configurações → Dispositivos e serviços → Adicionar integração**, procure **MMH Monitor**.

Só é permitida **uma instância** por Home Assistant.

### Atualizações

Cada versão é publicada como release no GitHub (`v0.1.0`, `v0.2.0`…). O HACS mostra "atualização disponível" no cliente; basta atualizar e reiniciar. As notas de cada versão estão no [CHANGELOG](CHANGELOG.md).

---

## Configuração

Toda a configuração é feita pela interface, sem YAML.

### Instalação

| Campo | Obrigatório | Observação |
|---|---|---|
| Identificador do site | sim | Minúsculas, números, `-` e `_` (ex.: `cliente-exemplo`). Vira a tag `site` no InfluxDB. |
| URL do InfluxDB | sim | Ex.: `https://influx.exemplo.com.br` |
| Organização | sim | Padrão `mmh` |
| Bucket | sim | Padrão `mmh_health` |
| Token | sim | Token **somente de escrita** criado para este site |
| URL de push do Kuma | não | Copiada do monitor Push do site no Uptime Kuma |

Antes de salvar, a integração grava um ponto de teste (`mmh_monitor_setup`) no InfluxDB. Se algo estiver errado, a tela informa: token inválido, organização/bucket não encontrados, falha de conexão ou URL inválida.

### Opções (⚙ Configurar)

| Opção | Padrão | Uso |
|---|---|---|
| Intervalo de coleta | 300 s | Entre 60 e 3600 s |
| URL dos limites remotos | — | JSON com limites próprios (veja [Limites](#limites)) |
| Entidades ignoradas | — | Padrões glob fora da contagem de indisponíveis (ex.: `media_player.tv_*`) |
| Entidades do coordenador Zigbee | — | Ex.: `binary_sensor.zigbee2mqtt_bridge_connection_state` |
| Entidade do último backup | — | Sensor de data/hora, para sites com backup próprio |
| Informar falha ao Kuma quando crítico | desligado | Envia `status=down` ao Kuma quando o nível geral for crítico |

### Reconfigurar

Em **⋮ → Reconfigurar** é possível trocar URL, organização, bucket, token e URL do Kuma sem remover a integração. Deixe o token vazio para manter o atual.

### Recomendações por site

- **Zigbee2MQTT:** informe a entidade de estado do bridge nas opções. Com ZHA não é preciso: a integração usa o estado da própria ZHA.
- **Backup:** a integração enxerga todos os backups que o HA conhece: os do agendamento nativo, os criados por automação (`hassio.backup_full`) e os manuais. Só informe uma entidade nas opções se o site usar uma ferramenta de backup externa que o HA não lista.
- **Entidades que ficam indisponíveis por natureza** (TVs desligadas, dispositivos sazonais): coloque-as em "Entidades ignoradas" para não gerar alerta falso.

---

## Entidades criadas

Todas ficam no dispositivo **MMH Monitor**. Os IDs são fixos e iguais em todo cliente, qualquer que seja o idioma do HA.

| Entidade | Estado | Atributos |
|---|---|---|
| `sensor.mmh_health` | `ok` / `atencao` / `critico` | `motivos`, `site`, `versao`, `ultima_coleta`, `ultimo_envio_ok` |
| `sensor.mmh_<checagem>` | valor medido (diagnóstico) | `nivel`, `mensagem`, `details` |
| `binary_sensor.mmh_problema` | ligado se o nível geral não for ok | `nivel` |
| `binary_sensor.mmh_envio_central` | ligado se o último envio ao InfluxDB funcionou (diagnóstico) | `ultimo_erro` |

Os atributos longos (`details`, `mensagem`, `motivos`) não são gravados no histórico do recorder, para não aumentar o banco do cliente.

---

## Checagens

Uma checagem que não se aplica ao site (sem `/proc`, banco MariaDB, sem Zigbee…) aparece como **não monitorado** e não afeta as demais.

Logo após o HA iniciar, as checagens que dependem de outras integrações (`integrations`, `unavailable_entities`, `zigbee`) ficam como não monitorado por 5 minutos, para um reinício não gerar alarme falso.

| Chave | Mede | Atenção | Crítico |
|---|---|---|---|
| `integrations` | Integrações com falha de carregamento (ignora as desabilitadas) | 1 | 3 |
| `unavailable_entities` | % de entidades `unavailable` (a contagem fica em `details`) | 5% | 15% |
| `disk_use` | % usado do disco do `/config` | 75% | 90% |
| `memory_use` | % de memória usada | 85% | 95% |
| `load_1m` | Carga de 1 minuto dividida pelo número de núcleos | 1.5 | 3.0 |
| `host_uptime` | Segundos desde o boot do host | — | — |
| `ha_uptime` | Segundos desde o início do HA (quedas = reinícios) | — | — |
| `system_log` | Erros registrados no log desde a coleta anterior | 5 | 20 |
| `recorder` | Tamanho do banco SQLite em MB (MariaDB/PostgreSQL: não monitorado) | 2000 | 5000 |
| `updates` | Atualizações pendentes (`details` indica se o HA Core está entre elas) | 1 | nunca |
| `backup` | Horas desde o último backup (qualquer origem). Crítico também se a última tentativa automática falhou | 384 (16 dias) | 720 (30 dias) |
| `zigbee` | Entidades do coordenador em estado de falha, ou ZHA com erro | — | 1 |

O **nível geral** (`sensor.mmh_health`) é o pior nível entre as checagens, ignorando as não monitoradas. A mensagem geral lista os motivos das que não estão ok.

Quando uma checagem fica **crítica**, a integração abre um aviso em **Configurações → Reparos**. O aviso some sozinho quando a checagem volta a ok ou atenção.

---

## Limites

Os limites acima são os padrões embutidos. Para ajustá-los sem publicar nova versão, aponte a opção **URL dos limites remotos** para um arquivo JSON:

```json
{
  "version": 1,
  "checks": {
    "disk_use": { "atencao": 70, "critico": 85 },
    "memory_use": { "atencao": 80 }
  },
  "sites": {
    "cliente-exemplo": {
      "disk_use": { "atencao": 80, "critico": 92 },
      "updates": { "atencao": null }
    }
  }
}
```

- **Precedência, campo a campo:** `sites.<slug>` > `checks` > padrão embutido. No exemplo, `memory_use` fica com atenção 80 e o crítico padrão 95.
- `null` desliga aquele limite.
- Um valor igual ao limite já o atinge (75% com atenção 75 = atenção).
- O arquivo é buscado ao iniciar e depois **a cada 6 horas**. O último arquivo válido fica em cache: se a rede cair ou o arquivo vier inválido, o site continua com os limites anteriores. Sem cache, valem os padrões.
- Há um exemplo completo em [docs/thresholds.example.json](docs/thresholds.example.json).

> ⚠️ O arquivo de limites lista os sites. **Não** o hospede neste repositório nem em local público.

---

## Dados enviados ao InfluxDB

Um `POST` por ciclo em `/api/v2/write?org=<org>&bucket=<bucket>&precision=s`, com todas as linhas:

```
mmh_check,check=<chave>,site=<slug> value=<float>,level=<int>i,msg="<texto>" <timestamp>
mmh_health,ha_version=<versão do HA>,site=<slug>,version=<versão da integração> level=<int>i,msg="<texto>" <timestamp>
```

| Campo | Tipo | Observação |
|---|---|---|
| `value` | float | Sempre float, para o tipo nunca mudar. Omitido quando a checagem não tem valor. |
| `level` | inteiro | `0` ok, `1` atenção, `2` crítico, `-1` não monitorado |
| `msg` | string | Motivo curto em pt-BR (até 250 caracteres) |

- Timeout de 10 s, sem nova tentativa no mesmo ciclo e sem fila em memória: o próximo ciclo envia de novo.
- InfluxDB e Kuma são independentes. Falha em um não impede o outro, e nenhuma falha de rede afeta o funcionamento do HA. Falhas repetidas são registradas no log no máximo uma vez por hora.
- Novas checagens apenas acrescentam valores na tag `check`. Mudanças que quebrem este esquema exigem nova versão **MAJOR**.

O Kuma recebe `GET <push_url>?status=up&msg=<nível>&ping=` a cada ciclo (ou `status=down` quando crítico, se a opção estiver ligada).

---

## Diagnóstico

Em **Configurações → Dispositivos e serviços → MMH Monitor → ⋮ → Baixar diagnóstico** é gerado um arquivo com a configuração, os limites em uso (e de onde vieram), o último resultado de cada checagem e o status dos envios. O token, a URL do Kuma e a URL dos limites saem redigidos.

---

## Segurança e privacidade

Este repositório é público e contém **apenas código**. Nenhum dado de cliente, token ou endereço da base central fica aqui.

- O token do InfluxDB, as URLs e o identificador do site são informados na interface e ficam salvos só no Home Assistant de cada cliente.
- Use **um token por cliente**, **somente de escrita** e restrito ao bucket de saúde. Um token vazado não lê dados e pode ser revogado individualmente.
- Use **um monitor Push do Kuma por cliente**. A URL de push funciona como senha: não a compartilhe nem mostre em prints.
- O token e as URLs do Kuma e dos limites nunca são gravados em log e são redigidos no diagnóstico.
- **Nunca** cole logs, diagnósticos ou prints de clientes em issues ou pull requests deste repositório.

---

## Desenvolvimento

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

O CI roda `hassfest`, a validação do HACS e o `pytest` em cada push e pull request.

### Versionamento e release

- SemVer (`MAJOR.MINOR.PATCH`). A versão em `custom_components/mmh_monitor/manifest.json` deve ser igual à tag (`v0.1.0` ↔ `"version": "0.1.0"`).
- Toda release tem entrada no [CHANGELOG](CHANGELOG.md).
- Fluxo: branch → PR → CI verde → merge na `main` → tag → GitHub Release.

## Licença

[MIT](LICENSE)
