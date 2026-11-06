# Servidor central (InfluxDB + Grafana)

Guia de referência do servidor que recebe os dados de todos os sites. Os endereços abaixo usam `exemplo.com.br`; troque pelo domínio real.

> Este repositório é público. **Não** registre aqui hostnames reais, IDs de túnel, tokens ou senhas.

## Arquitetura

```
HAs dos clientes ──HTTPS──► Cloudflare ──Tunnel──► VM
                             │                      ├─ InfluxDB 2  (127.0.0.1:8086)
                             │                      ├─ Grafana     (127.0.0.1:3000)
                             │                      └─ Uptime Kuma (127.0.0.1:3001)
                             └─ Cloudflare Access: login por e-mail em tudo,
                                exceto /api/v2/write (liberado, exige token)
```

- Nenhuma porta da VM fica exposta à internet: tudo passa pelo Cloudflare Tunnel.
- Os HAs só conseguem **escrever**, com um token por site.
- Grafana e a interface do InfluxDB exigem login do Cloudflare Access.

## 1. Máquina

Para o piloto, uma VM pequena (1 GB de RAM) funciona com swap e limites de memória. Para dezenas de sites, use 2 GB ou mais.

```bash
# Swap de 2 GB (rodar uma única vez)
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf && sudo sysctl -p /etc/sysctl.d/99-swap.conf
```

## 2. InfluxDB e Grafana (Docker Compose)

Em `/opt/mmh-central`, gere as senhas na própria máquina (os arquivos ficam legíveis só pelo root):

```bash
sudo mkdir -p /opt/mmh-central && cd /opt/mmh-central
printf 'DOCKER_INFLUXDB_INIT_USERNAME=admin\nDOCKER_INFLUXDB_INIT_PASSWORD=%s\nDOCKER_INFLUXDB_INIT_ADMIN_TOKEN=%s\n' "$(openssl rand -hex 16)" "$(openssl rand -hex 32)" | sudo tee influx.env >/dev/null
printf 'GF_SECURITY_ADMIN_USER=admin\nGF_SECURITY_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 16)" | sudo tee grafana.env >/dev/null
sudo chmod 600 influx.env grafana.env
```

`/opt/mmh-central/docker-compose.yml`:

```yaml
services:
  influxdb:
    image: influxdb:2.7
    container_name: influxdb
    restart: unless-stopped
    ports:
      - "127.0.0.1:8086:8086"
    env_file: influx.env
    environment:
      DOCKER_INFLUXDB_INIT_MODE: setup
      DOCKER_INFLUXDB_INIT_ORG: mmh
      DOCKER_INFLUXDB_INIT_BUCKET: mmh_health
      DOCKER_INFLUXDB_INIT_RETENTION: 400d
      INFLUXD_REPORTING_DISABLED: "true"
      INFLUXD_STORAGE_CACHE_MAX_MEMORY_SIZE: "67108864"
      INFLUXD_STORAGE_CACHE_SNAPSHOT_MEMORY_SIZE: "16777216"
      GOMEMLIMIT: 220MiB
    volumes:
      - influxdb-data:/var/lib/influxdb2
      - influxdb-config:/etc/influxdb2
    mem_limit: 320m

  grafana:
    image: grafana/grafana-oss:12.0.0
    container_name: grafana
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:3000"
    env_file: grafana.env
    environment:
      GF_SERVER_ROOT_URL: https://grafana.exemplo.com.br
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
      GF_PLUGINS_PREINSTALL_DISABLED: "true"
      GOMEMLIMIT: 150MiB
    volumes:
      - grafana-data:/var/lib/grafana
    depends_on:
      - influxdb
    mem_limit: 220m

volumes:
  influxdb-data:
  influxdb-config:
  grafana-data:
```

```bash
cd /opt/mmh-central && sudo docker compose up -d
curl -s http://127.0.0.1:8086/health        # "status":"pass"
curl -s http://127.0.0.1:3000/api/health    # "database":"ok" (a primeira partida pode levar ~1 min)
```

O bucket `mmh_health` guarda 400 dias, o que permite comparar períodos ano a ano.

## 3. Cloudflare Tunnel

Acrescente as regras ao `config.yml` do túnel, **antes** da regra final `http_status:404`:

```yaml
  - hostname: influx.exemplo.com.br
    service: http://localhost:8086
  - hostname: grafana.exemplo.com.br
    service: http://localhost:3000
```

```bash
sudo cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
sudo cloudflared tunnel --origincert /etc/cloudflared/cert.pem route dns <nome-do-túnel> influx.exemplo.com.br
sudo systemctl restart cloudflared
```

Crie o DNS do Grafana **depois** de configurar o Access (passo 4).

## 4. Cloudflare Access

Em **Zero Trust → Access → Aplicativos → Auto-hospedado**:

| Aplicativo | Destino | Política |
|---|---|---|
| Grafana | `grafana.exemplo.com.br` | Permitir: e-mails da equipe |
| InfluxDB UI | `influx.exemplo.com.br` | Permitir: e-mails da equipe |
| InfluxDB write | `influx.exemplo.com.br/api/v2/write` | **Ignorar (Bypass)**: Todos |

O Access avalia o bypass primeiro, então só o caminho de escrita passa sem login, e ele continua exigindo token.

Teste:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://grafana.exemplo.com.br/   # 302 (login)
curl -s -o /dev/null -w "%{http_code}\n" https://influx.exemplo.com.br/    # 302 (login)
curl -s -o /dev/null -w "%{http_code}\n" -X POST "https://influx.exemplo.com.br/api/v2/write?org=mmh&bucket=mmh_health"   # 401 (pede token)
```

## 5. Grafana

1. Senha do admin, na VM: `sudo grep PASSWORD /opt/mmh-central/grafana.env`.
2. **Connections → Data sources → InfluxDB**: linguagem **Flux**, URL `http://influxdb:8086`, organização `mmh`, token de **leitura**, bucket `mmh_health`. Deixe **Basic auth desligado**.
3. **Dashboards → Import**: envie [grafana/mmh-monitor-dashboard.json](grafana/mmh-monitor-dashboard.json) e escolha o data source.

Token de leitura para o Grafana:

```bash
BID=$(sudo docker exec influxdb influx bucket list --org mmh --name mmh_health --hide-headers | awk '{print $1}')
sudo docker exec influxdb influx auth create --org mmh --read-bucket "$BID" --description "grafana read"
```

## 6. Novo cliente

1. **Token de escrita do site** (aparece uma vez; copie direto para o HA do cliente):
   ```bash
   SITE=cliente-exemplo
   BID=$(sudo docker exec influxdb influx bucket list --org mmh --name mmh_health --hide-headers | awk '{print $1}')
   sudo docker exec influxdb influx auth create --org mmh --write-bucket "$BID" --description "site:$SITE write"
   ```
2. **Uptime Kuma:** novo monitor **Push**, nome `MMH <site>`, intervalo de heartbeat de **360 s** (coleta de 5 min + folga). Copie a URL de push.
3. **HA do cliente:** instale pelo HACS e configure (veja o [README](../README.md#configuração)).
4. Confira os dados:
   ```bash
   sudo docker exec influxdb influx query --org mmh 'from(bucket:"mmh_health") |> range(start:-15m) |> filter(fn:(r)=> r.site=="cliente-exemplo" and r._field=="level") |> last() |> keep(columns:["check","_value"])'
   ```

### Revogar o token de um site

```bash
sudo docker exec influxdb influx auth list --org mmh | grep "site:cliente-exemplo"
sudo docker exec influxdb influx auth delete --id <ID>
```

Depois gere um novo token e atualize o HA do cliente em **⋮ → Reconfigurar**.

## 7. Manutenção

- **Atualizar imagens:** `cd /opt/mmh-central && sudo docker compose pull && sudo docker compose up -d`.
- **Backup:** os dados ficam nos volumes Docker `mmh-central_influxdb-data` e `mmh-central_grafana-data`. Um backup lógico do InfluxDB:
  ```bash
  sudo docker exec influxdb influx backup /var/lib/influxdb2/backup-$(date +%F) && sudo docker cp influxdb:/var/lib/influxdb2/backup-$(date +%F) ./
  ```
- **Memória:** `sudo docker stats --no-stream`. Se o swap ficar alto com frequência, aumente a VM: os dados ficam no disco e nada precisa ser reinstalado.
