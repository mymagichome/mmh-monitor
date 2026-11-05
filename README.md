# MMH Monitor

Integração customizada do Home Assistant que monitora a saúde de cada instância HA de cliente da My Magic Home (MMH). Ela envia métricas para o InfluxDB central e um heartbeat para o Uptime Kuma.

> **Status:** em desenvolvimento (rumo à `v0.1.0`). Ainda não deve ser instalada em clientes.

## Instalação (HACS)

1. No HACS, abra o menu ⋮ → **Repositórios personalizados**.
2. Adicione `https://github.com/mymagichome/mmh-monitor` com a categoria **Integração**.
3. Instale **MMH Monitor** e reinicie o Home Assistant.
4. Em **Configurações → Dispositivos e serviços → Adicionar integração**, procure por **MMH Monitor**.

Versão mínima do Home Assistant: **2026.3.4**.

## Desenvolvimento

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

A documentação completa (configuração, entidades, esquema de dados e limites) chega na Fase 5.

## Licença

[MIT](LICENSE)
