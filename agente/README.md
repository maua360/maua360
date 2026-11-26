# Agente de notícias – Mauá e Grande ABC

Script em Python que, de tempos em tempos:

1. **Coleta** notícias de fontes regionais (RSS com `feedparser`, páginas sem RSS com `requests` + `BeautifulSoup`);
2. **Descarta duplicadas** (SQLite, por URL normalizada e por título normalizado, então a mesma pauta vinda de dois veículos só entra uma vez);
3. **Filtra por relevância** com palavras-chave locais, **antes** de gastar tokens;
4. **Reescreve** com o Claude (persona de repórter local), recebendo um JSON validado com `titulo`, `subtitulo`, `conteudo_html`, `categoria` e `tags`;
5. **Envia como rascunho**: por padrão abre um Pull Request no repositório do site estático Mauá 360 (`PUBLISHER=github`, ver `github_publisher.py` e o README do `maua360-site`); com `PUBLISHER=wordpress`, cria rascunho no WordPress pela REST API.

Nada é publicado automaticamente: tudo cai em **Posts > Rascunhos** para revisão humana.

## Estrutura

| Arquivo | Função |
|---|---|
| `main.py` | Orquestra o fluxo; modos `--once` (padrão), `--loop`, `--dry-run`, `--check` |
| `scraper.py` | Coleta RSS/HTML e extrai o texto completo da matéria |
| `relevance.py` | Filtro de palavras-chave com pesos (Mauá, bairros, Grande ABC, Linha 10) |
| `ai_writer.py` | Chamada ao Claude com saída estruturada + limpeza do HTML + checagem de números |
| `wp_publisher.py` | Cria categoria/tags se faltarem e envia o post como rascunho |
| `database.py` | SQLite de controle (descartadas, rascunhos, erros) |
| `config.py` | Lê o `.env` |
| `sources.json` | Lista de fontes, editável sem mexer no código |

## Instalação

```bash
cd portal-maua
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # preencha as chaves
```

### WordPress
1. Crie um usuário com papel **Editor** (ou Autor) só para o robô.
2. Em *Usuários > Perfil > Senhas de aplicativo*, gere uma senha e cole em `WP_APP_PASSWORD`.
3. O site precisa estar em HTTPS (exigência do WordPress para Application Passwords).
4. Categorias usadas: **Notícias, Política, Esportes, Entretenimento, Saúde**. Se não existirem, o agente cria (desligue com `WP_CREATE_MISSING_TERMS=false`).

### Claude
- `CLAUDE_MODEL=claude-sonnet-5-5` (padrão, melhor texto) ou `claude-haiku-5-5` (bem mais barato, bom para volume).
  Os modelos `claude-3-5-sonnet-latest` / `haiku` citados no pedido foram **aposentados** pela Anthropic e não respondem mais.
- A resposta usa *structured outputs* (`client.beta.messages.parse` com um modelo Pydantic): a API garante JSON no formato certo, sem precisar "pedir JSON" e torcer.
- `CLAUDE_FALLBACK=true` ativa o fallback de recusa do servidor: se um filtro de segurança recusar um texto (raro, mas acontece com notícias policiais), a API refaz a chamada em outro modelo automaticamente.

## Uso

```bash
python main.py --check      # testa WordPress e fontes, sem gastar tokens
python main.py --dry-run    # roda tudo, mas salva o JSON em output/ em vez de enviar ao WP
python main.py              # execução única (use no cron)
python main.py --loop       # fica rodando a cada LOOP_INTERVAL_MINUTES
```

### Cron (a cada 30 min)
```cron
*/30 * * * * cd /caminho/portal-maua && .venv/bin/python main.py >> logs/cron.log 2>&1
```

Logs ficam em `logs/agente.log` (rotação automática, 5 arquivos de 2 MB).

## Anti-alucinação

- O prompt proíbe qualquer fato, número, nome ou citação que não esteja no texto-fonte.
- Depois da resposta, `unverified_numbers()` compara os números do texto novo com os da fonte. Se aparecer um número que não estava lá, o rascunho recebe um comentário `<!-- REVISAR: ... -->` no topo (visível no editor, invisível no site) e um aviso no log.
- Matérias com menos de 300 caracteres de texto útil não são enviadas ao Claude (pouco material = mais risco de inventar).
- Todo post leva o crédito "Com informações de <fonte>" com link.

## Fontes (`sources.json`)

| Fonte | Tipo | Situação em 26/11/2026 |
|---|---|---|
| Diário do Grande ABC | RSS `dgabc.com.br/Servicos/RSS/Home` | Feed confirmado (geral, todas as editorias; o filtro separa Mauá) |
| ABC do ABC | RSS `wp.abcdoabc.com.br/feed/noticias` | Feed confirmado |
| Google Notícias (busca "Mauá SP") | RSS | Formato padrão do Google; usa só título/resumo |
| Prefeitura de Mauá | HTML | **Sem RSS conhecido – confira URL e seletores** |
| Câmara de Mauá | HTML | **Confira URL e seletores** |
| CPTM (Linha 10) | HTML | **Confira URL e seletores** |

Para as fontes HTML: abra a página de listagem no navegador, clique com o botão direito num título > *Inspecionar*, e ajuste `link_selector` (os links das matérias) e `content_selector` (o bloco do texto). Depois rode `python main.py --check`.

Para adicionar um portal novo, basta incluir um item em `sources.json`. Muitos sites em WordPress têm feed em `/feed/`.

## Ajuste fino

- **Palavras-chave**: edite os dicionários em `relevance.py` (bairros, nomes, órgãos). Pesos negativos derrubam conteúdo patrocinado e "Mauá" que não é a cidade (Barão de Mauá, Mauá-RJ).
- **Custo**: `MAX_ARTICLES_PER_RUN` limita quantas matérias vão para o Claude por execução. Com Haiku 5.5, uma matéria típica custa uma fração de centavo de dólar; com Sonnet 5.5, alguns centavos.
- **Prioridade Mauá**: pautas de Mauá passam na frente; no máximo `MAX_ABC_PER_RUN` (padrão 1) pautas só do resto do ABC entram por execução, como complemento.
- **Política Brasil/SP**: matérias de política nacional ou do Estado (UOL, Metrópoles e outras fontes) entram depois das locais, na editoria Política, até `MAX_POLITICA_PER_RUN` (padrão 2) por execução; `MIN_POLITICA_PER_RUN` (padrão 1) vaga fica garantida em toda execução.
- **Fontes**: `sources.json`; cada fonte tem uma `nota` dizendo como foi testada. Para testar de novo, rode o workflow "Testar fontes" no Actions.
- **Reprocessar erros**: matérias com status `erro` voltam a ser tentadas na execução seguinte; `descartada` e `rascunho` não.

## Cuidados legais e editoriais

- Reescrever não elimina a obrigação de **checar a informação** e de **creditar a fonte**. Mantenha a revisão humana antes de publicar.
- Respeite o `robots.txt` e os termos de uso de cada portal, e mantenha o intervalo de coleta razoável (30 min ou mais).
- O portal "Sobre ABC" serviu apenas como referência de editorias; o agente não coleta conteúdo dele.
