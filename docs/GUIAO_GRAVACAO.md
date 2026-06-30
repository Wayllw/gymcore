# Guião de Gravação — GymCore Fase 3

Este guião está organizado para gravares por blocos. Cada bloco demonstra
um padrão arquitetural específico, com o "porquê" pronto para dizeres em
voz alta enquanto mostras o terminal.

**Preparação antes de gravar:**
```bash
cd gymcore-fase3
docker-compose up --build
```
Deixa correr numa janela de terminal **visível durante toda a gravação**
— os logs em tempo real são a prova de que tudo está a funcionar. Abre
um segundo terminal para os comandos `curl`.

Sugestão de instalação do `jq` para formatar JSON (opcional mas ajuda muito
na leitura durante a gravação):
```bash
sudo apt install jq      # Linux
# ou usa: python -m json.tool em vez de jq
```

---

## Bloco 1 — Arranque e Health Checks (30s)

**Dizer:** "Aqui temos os 3 serviços a correr em contentores Docker separados: o Gateway, o Sócios-Service com REST e gRPC, e o Treinos-Service. Cada um é independente."

```bash
curl -s http://localhost:8000/health | jq
curl -s http://localhost:8001/health | jq
curl -s http://localhost:8002/health | jq
```

Repara no campo `circuit_breaker_estado: "closed"` na resposta do Treinos-Service — vamos voltar a este campo no Bloco 5.

---

## Bloco 2 — Inscrição de Sócio + Saga "Inscrição Completa" (1min)

**Dizer:** "Vou inscrever um sócio através do Gateway. Por trás, isto vai disparar uma Saga coreografada — o Sócios-Service publica um evento, e o Treinos-Service reage criando automaticamente um plano de treino inicial, sem que eu peça isso explicitamente."

```bash
curl -s -X POST http://localhost:8000/socios \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: demo-saga-001" \
  -d '{"nome":"Sofia Mendes","email":"sofia@gym.pt","data_nascimento":"1998-02-10","plano":"PREMIUM"}' | jq
```

Guarda o `id` da resposta (vamos chamá-lo `SOCIO_ID` no resto do guião).

**Dizer:** "Vou olhar para os logs em tempo real — repara como o mesmo correlationId 'demo-saga-001' aparece nos dois serviços, mesmo sendo processos completamente separados."

*(apontar para a janela com docker-compose logs)* — deves ver algo como:
```
socios-service   | Sócio inscrito: id=... | correlation_id=demo-saga-001
socios-service   | Evento publicado | tipo=socio.inscrito | correlation_id=demo-saga-001
treinos-service  | socio.inscrito recebido | correlation_id=demo-saga-001
treinos-service  | gRPC ValidarSocio | correlation_id=demo-saga-001
socios-service   | Sócio validado | ativo=True | correlation_id=demo-saga-001
treinos-service  | Plano inicial criado | correlation_id=demo-saga-001
```

**Dizer:** "Vou confirmar que o plano foi mesmo criado, sem eu ter chamado o endpoint de criação de planos."

```bash
sleep 2
curl -s http://localhost:8000/socios/SOCIO_ID/planos-treino | jq
```

Deves ver o "Plano Inicial de Adaptação" com 3 exercícios — criado automaticamente pela Saga.

---

## Bloco 3 — Criação Manual de Plano + Validação gRPC (45s)

**Dizer:** "Agora vou criar um plano manualmente. Antes de o Treinos-Service guardar este plano, ele faz uma chamada gRPC síncrona ao Sócios-Service para confirmar que este sócio existe e está ativo."

```bash
curl -s -X POST http://localhost:8000/socios/SOCIO_ID/planos-treino \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: demo-grpc-001" \
  -d '{"nome":"Plano Hipertrofia","nivel":"AVANCADO","exercicios":[{"nome":"Supino Reto","series":4,"repeticoes":8,"descanso_segundos":90,"tipo":"FORCA"}]}' | jq
```

*(apontar para os logs)* — deves ver a entrada gRPC nos logs do Sócios-Service.

**Dizer:** "E agora vou tentar criar um plano para um sócio que não existe, para mostrar a validação a rejeitar."

```bash
curl -s -w "\nHTTP_STATUS: %{http_code}\n" -X POST http://localhost:8000/socios/00000000-0000-0000-0000-000000000000/planos-treino \
  -H "Content-Type: application/json" \
  -d '{"nome":"Plano Fantasma","nivel":"INICIANTE","exercicios":[]}'
```

Deves ver `HTTP_STATUS: 422` e a mensagem "Sócio não encontrado".

---

## Bloco 4 — Endpoint Agregado no Gateway (20s)

**Dizer:** "O Gateway também sabe agregar dados de dois serviços diferentes numa só resposta, sem que os serviços se conheçam um ao outro."

```bash
curl -s http://localhost:8000/socios/SOCIO_ID/completo | jq
```

Mostra o sócio + os 2 planos (inicial automático + hipertrofia manual) numa única resposta.

---

## Bloco 5 — Circuit Breaker: a parte mais importante para mostrar (1min30s)

**Dizer:** "Agora vou demonstrar resiliência. Vou simular o Sócios-Service a cair e mostrar o Circuit Breaker do Treinos-Service a reagir."

```bash
docker-compose stop socios-service
```

**Dizer:** "Vou tentar criar planos repetidamente. As primeiras tentativas vão demorar mais — estão a tentar mesmo contactar a rede e a esperar pelo timeout. Depois de 3 falhas, o circuito abre e as respostas tornam-se imediatas."

```bash
for i in 1 2 3 4 5; do
  echo "--- Tentativa $i ---"
  time curl -s -w "\nHTTP_STATUS: %{http_code}\n" -X POST http://localhost:8000/socios/SOCIO_ID/planos-treino \
    -H "Content-Type: application/json" \
    -d '{"nome":"Plano Teste","nivel":"INICIANTE","exercicios":[]}'
  echo
done
```

*(apontar para os logs do treinos-service)* — deves ver as transições:
```
🔌 [CIRCUIT-BREAKER:SocioValidationService] Falha registada (1/3)
🔌 [CIRCUIT-BREAKER:SocioValidationService] Falha registada (2/3)
🔌 [CIRCUIT-BREAKER:SocioValidationService] Falha registada (3/3)
🔌 [CIRCUIT-BREAKER:SocioValidationService] Transição de estado: CLOSED → OPEN
```

**Dizer:** "Repara que da 4ª tentativa em diante, a resposta é praticamente instantânea — o circuito está aberto e nem tenta a rede. Vou confirmar isto no health check."

```bash
curl -s http://localhost:8002/health | jq
```

Deve mostrar `"circuit_breaker_estado": "open"`.

**Dizer:** "Agora vou repor o Sócios-Service e mostrar o circuito a recuperar."

```bash
docker-compose start socios-service
sleep 12   # aguardar o reset_timeout de 10s do circuito
curl -s -X POST http://localhost:8000/socios/SOCIO_ID/planos-treino \
  -H "Content-Type: application/json" \
  -d '{"nome":"Plano Recuperado","nivel":"INICIANTE","exercicios":[]}' | jq

curl -s http://localhost:8002/health | jq
```

Deve voltar a `"circuit_breaker_estado": "closed"`.

---

## Bloco 6 — Saga: caminho de falha e compensação (1min)

**Dizer:** "Por último, vou mostrar o que acontece quando a Saga falha a meio — quando o sócio existe mas, por exemplo, o serviço de validação está em baixo no momento da inscrição."

```bash
docker-compose stop socios-service
```

Espera 1-2 segundos para o stop ser aplicado, depois:

```bash
# Inserir o sócio diretamente seria complicado com socios-service parado.
# Em alternativa, demonstra o cenário "sócio suspenso/inexistente":
docker-compose start socios-service
sleep 3
```

**Dizer:** "Vou agora simular o outro cenário de falha da Saga: um sócio que entretanto deixou de ser válido. Vou suspendê-lo e depois publicar manualmente o evento que dispara a Saga, para mostrar a compensação a ser aplicada do lado do Sócios-Service."

```bash
curl -s -X POST http://localhost:8000/socios/SOCIO_ID/suspender | jq
```

*(Nota: para republicar o evento `socio.inscrito` manualmente exigiria aceder
ao Redis diretamente — opcional, mas se quiseres mostrar isto ao vivo)*:

```bash
docker exec -it gymcore-redis redis-cli XADD stream:socios '*' \
  tipo socio.inscrito \
  payload "{\"socio_id\":\"SOCIO_ID\",\"nome\":\"Sofia Mendes\",\"email\":\"sofia@gym.pt\"}" \
  correlation_id demo-falha-saga-001 \
  timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  origem socios-service
```

*(apontar para os logs)* — deves ver no Treinos-Service:
```
🟡 [SAGA] Sócio inválido para plano inicial | motivo=Sócio está SUSPENSO
```
E no Sócios-Service:
```
🔧 [SAGA-COMPENSACAO] Sócio ... marcado para acompanhamento manual
```

**Dizer:** "Aqui está a compensação da Saga: em vez de desfazer a inscrição, o Sócios-Service marca o sócio para acompanhamento manual por um funcionário — é uma decisão de negócio, não um rollback técnico."

```bash
curl -s http://localhost:8000/socios/SOCIO_ID/acompanhamento | jq
```

---

## Bloco 7 — Testes Automatizados (30s, opcional mas valioso para a defesa)

**Dizer:** "Por fim, todo o Core de cada serviço é testável sem qualquer infraestrutura real — usando fakes em memória."

```bash
docker-compose down  # ou Ctrl+C no terminal dos logs

cd socios-service && python -m pytest tests/ -v
cd ../treinos-service && python -m pytest tests/ -v
cd .. && python -m pytest tests/integration/ -v   # este já usa gRPC real
```

---

## Checklist do que mostrar (resumo para não esquecer nada)

- [ ] 3 serviços a correr em contentores separados (`docker-compose up`)
- [ ] Health checks dos 3 serviços
- [ ] Inscrição de sócio → Saga cria plano inicial automaticamente
- [ ] correlationId visível nos logs de **ambos** os serviços para o mesmo pedido
- [ ] Criação manual de plano com validação gRPC bem-sucedida
- [ ] Validação gRPC a rejeitar sócio inexistente (422)
- [ ] Endpoint agregado `/completo`
- [ ] Circuit Breaker: falhas a abrir o circuito + resposta rápida depois
- [ ] Circuit Breaker: estado visível no `/health`
- [ ] Circuit Breaker: recuperação após `reset_timeout`
- [ ] Saga: caminho de falha + compensação (acompanhamento manual)
- [ ] Testes automatizados a passar (opcional)

## Dicas para a gravação

- Usa **dois terminais lado a lado**: um só com os logs do `docker-compose up` sempre visível, outro para os comandos. É a forma mais clara de provar visualmente o que está "por trás" de cada `curl`.
- Se o ecrã ficar com muito log, podes filtrar por serviço numa janela extra: `docker-compose logs -f treinos-service`.
- Fala sempre o "porquê" antes do "como" — primeiro explica que padrão vais mostrar, só depois corres o comando.
- Não precisas de gravar tudo de uma vez — podes cortar entre blocos, desde que cada bloco demonstre claramente o padrão e o resultado.
