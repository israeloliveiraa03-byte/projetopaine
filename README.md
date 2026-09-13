# Atualização automática do Raizame Dados

Este pacote deixa o painel se atualizando sozinho, uma vez por semana, direto
da planilha pública do Google Sheets.

## Como funciona

1. Toda segunda-feira às 02h00 (UTC), o GitHub roda o script `atualizar_dados.py`.
2. O script baixa a aba "CERTIFICADAS" da planilha em CSV, limpa os dados,
   geocodifica cada município (usando a mesma tabela de coordenadas que já
   usamos antes) e gera um `index.html` novo a partir do `template.html`.
3. Se o `index.html` gerado for diferente do que já está no repositório
   (ou seja, a planilha mudou), o robô commita e sobe essa mudança sozinho.
4. Como a Vercel já está ligada ao seu repositório, ela publica a nova
   versão automaticamente, sem você precisar fazer nada.
5. Se a planilha não mudou naquela semana, o robô não commita nada
   (sem poluir o histórico do repositório com commits vazios).

## O que colocar no seu repositório

Coloque estes quatro itens na raiz do repositório:

- `index.html` — a versão mais atual do painel, já com todos os dados
  embutidos (mapa, filtro de situação da titulação, nome "Raizame Dados"
  etc.). Se você já tem um `index.html` no repositório, pode sobrescrever
  pelo deste pacote, para começar do mesmo ponto.
- `atualizar_dados.py` — o script que baixa, limpa e regenera a página.
- `template.html` — o mesmo painel, mas sem os dados embutidos (com os
  marcadores `__TOTAL_REGISTROS__`, `__DATA_JSON__` etc. que o script
  preenche sozinho). É a partir dele que o script gera um `index.html`
  novo a cada execução.
- `.github/workflows/atualizacao-semanal.yml` — o agendamento em si.
  **Importante:** esse arquivo precisa ficar exatamente no caminho
  `.github/workflows/atualizacao-semanal.yml` dentro do repositório
  (crie as pastas `.github` e `workflows` se ainda não existirem).

## Configuração única, antes de funcionar

No GitHub, vá em **Settings → Actions → General → Workflow permissions**
do seu repositório e marque **"Read and write permissions"**. Sem isso,
o robô consegue rodar o script mas não consegue commitar o resultado de
volta (o GitHub bloqueia por padrão, por segurança).

## Testando sem esperar a semana

Depois de subir os três arquivos, vá na aba **Actions** do repositório,
escolha o workflow "Atualização semanal dos dados (Raizame Dados)" e
clique em **"Run workflow"** para disparar manualmente e conferir que
tudo funciona antes de deixar no piloto automático.

## Se algo mudar na planilha oficial

Se um dia a FCP renomear uma coluna da planilha (por exemplo, mudar
"Nº DE CRQ" para outro nome), o script vai avisar no log da Action
("coluna 'X' não encontrada") em vez de quebrar silenciosamente. Basta
abrir `atualizar_dados.py`, achar o dicionário `MAPA_COLUNAS` perto do
topo do arquivo, e ajustar o nome da coluna ali.

Como trava de segurança, se por qualquer motivo a planilha vier vazia
ou cortada (erro de rede, mudança de permissão etc.), o script aborta
e **não** sobrescreve o `index.html` que já está publicado — ele só
publica quando confirma ter recebido um volume de registros consistente
com o esperado.

## Trocar o dia/horário da atualização

No arquivo `.github/workflows/atualizacao-semanal.yml`, a linha:

```yaml
- cron: "0 2 * * 1"
```

controla quando o robô roda (nesse exemplo: toda segunda-feira às 02h00
UTC, ou seja, domingo às 23h em Brasília). O formato é
`minuto hora dia-do-mês mês dia-da-semana`, sempre em UTC.
