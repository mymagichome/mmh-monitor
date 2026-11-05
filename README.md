# MMH Monitor

Integração customizada do Home Assistant que monitora a saúde de cada instância HA de cliente da My Magic Home (MMH). Ela envia métricas para o InfluxDB central e um heartbeat para o Uptime Kuma.

> **Status:** em desenvolvimento (rumo à `v0.1.0`). Ainda não deve ser instalada em clientes.

## Instalação (HACS)

1. No HACS, abra o menu ⋮ → **Repositórios personalizados**.
2. Adicione `https://github.com/mymagichome/mmh-monitor` com a categoria **Integração**.
3. Instale **MMH Monitor** e reinicie o Home Assistant.
4. Em **Configurações → Dispositivos e serviços → Adicionar integração**, procure por **MMH Monitor**.

Versão mínima do Home Assistant: **2026.3.4**.

## Segurança e privacidade

Este repositório é público e contém **apenas código**. Nenhum dado de cliente, token ou endereço da base central fica aqui.

- O token do InfluxDB, a URL do InfluxDB, a URL do Kuma e o identificador do site são informados na interface, durante a instalação, e ficam salvos só no Home Assistant de cada cliente.
- Use **um token por cliente**, **somente de escrita** e restrito ao bucket de saúde. Um token vazado não lê dados e pode ser revogado individualmente.
- Use **um monitor Push do Kuma por cliente**.
- O token e a URL do Kuma nunca são gravados em log e são redigidos no diagnóstico.
- O JSON de limites remotos (que pode listar sites) **não** deve ser hospedado neste repositório nem em local público.
- **Nunca** cole logs, diagnósticos ou prints de clientes em issues ou pull requests deste repositório.

## Desenvolvimento

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

A documentação completa (configuração, entidades, esquema de dados e limites) chega na Fase 5.

## Licença

[MIT](LICENSE)
