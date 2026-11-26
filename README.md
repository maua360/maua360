# Mauá 360 — site

Site estático do portal Mauá 360 (maua360.com.br), hospedado de graça no Cloudflare Pages.
Não usa WordPress: cada matéria é um arquivo `.json` em `content/posts/`, e o `build.py`
(só Python, sem instalar nada) gera o site em `public/`.

## Como as matérias chegam ao ar

1. O agente (pasta `portal-maua`) coleta, reescreve com o Claude e abre um **Pull Request** neste repositório, um por matéria.
2. O Cloudflare Pages cria um **link de prévia** para cada PR (aparece como comentário no PR).
3. Você revisa pelo celular (app do GitHub) ou computador:
   - **Merge** = publica (o site atualiza em ~1 minuto);
   - lápis em *Files changed* = corrigir o texto antes;
   - **Close** = descartar.

Para escrever uma matéria à mão: copie um arquivo de `content/posts/`, mude os campos e faça commit.

## Estrutura

| Caminho | O que é |
|---|---|
| `site.json` | Nome, slogan, WhatsApp, e-mails, redes, editorias |
| `content/posts/*.json` | Matérias (`status: "rascunho"` esconde a matéria) |
| `content/paginas/*.html` | Sobre, Expediente, Política Editorial, Contato, Anuncie, Privacidade |
| `static/` | CSS, logos, favicon, imagem padrão de compartilhamento |
| `build.py` | Gera `public/` com home, editorias, tags, matérias, RSS, sitemaps |

Campos de uma matéria: `titulo`, `subtitulo`, `categoria` (Notícias, Política, Esportes,
Entretenimento ou Saúde), `tags`, `data` (ISO, horário de Brasília), `slug`, `autor`,
`conteudo_html`, e opcionais `imagem` (URL), `imagem_legenda`, `fonte_nome`, `fonte_url`.

Testar no computador: `python3 build.py --serve` e abrir http://localhost:8000.

## Colocar no ar (uma vez só)

1. **Cloudflare**: crie uma conta grátis em cloudflare.com, clique em *Add a domain* e digite `maua360.com.br` (plano Free).
   A Cloudflare mostra dois *nameservers*.
2. **Registro.br**: em *maua360.com.br > DNS > Alterar servidores DNS*, cole os dois nameservers da Cloudflare.
   A troca leva de minutos a algumas horas.
3. **Cloudflare Pages**: *Workers & Pages > Create > Pages > Connect to Git*, escolha o repositório `maua360`.
   - Build command: `python3 build.py`
   - Build output directory: `public`
   - Depois do primeiro deploy: *Custom domains* > adicionar `maua360.com.br` e `www.maua360.com.br`.
4. **E-mails grátis**: na Cloudflare, *Email > Email Routing*, ative e crie `redacao@`, `comercial@` e
   `privacidade@maua360.com.br` encaminhando para o seu Gmail. Para responder como redacao@, configure
   "Enviar e-mail como" no Gmail.
5. **Google**: cadastre o site no Search Console e envie `sitemap.xml` e `sitemap-noticias.xml`.

## Ligar o agente

1. No GitHub: *Settings > Developer settings > Fine-grained tokens > Generate*, só para o repositório
   `maua360`, com **Contents** e **Pull requests** em *Read and write*.
2. No `.env` do agente: `PUBLISHER=github`, `GITHUB_REPO=seuusuario/maua360`, `GITHUB_TOKEN=...`.
3. `python main.py --check`, depois `python main.py`.

## Pendências

- Trocar o WhatsApp de exemplo em `site.json` e nas páginas Contato/Anuncie (`5511900000000`).
- Preencher o endereço em `content/paginas/expediente.html`.
- Colocar o link do canal de WhatsApp em `site.json` quando ele existir.
