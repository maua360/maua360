# Redes sociais e imagens

Quando você clica em **Merge** num PR de rascunho, o workflow **Redes sociais** (`.github/workflows/redes.yml`):

1. usa a foto que você anexou num comentário do PR (pelo celular ou computador); se não houver, busca uma foto livre no Openverse (Wikimedia Commons, Flickr etc.), só com licença CC0, domínio público ou CC BY, e põe autor, origem e licença no crédito. Não precisa de chave;
2. desenha o cartão da matéria (1080x1350) em `static/cards/<slug>.jpg`, com logo, editoria e título;
3. grava a foto e o cartão no JSON da matéria (`imagem`, `imagem_legenda`, `imagem_social`) e faz o commit;
4. espera o site publicar e posta o cartão no Facebook (com o link) e no Instagram (com "link na bio").

Sem os segredos da Meta, ele faz só os passos 1 a 3. Nunca usamos fotos dos veículos de origem.

## Segredos (Settings > Secrets and variables > Actions)

| Nome | O que é |
|---|---|
| `META_PAGE_ID` | ID da página do Facebook "Mauá 360" |
| `META_PAGE_TOKEN` | Token de acesso da página (o de longa duração, que não expira) |
| `META_IG_USER_ID` | ID da conta do Instagram @portalmaua360 ligada à página |

Variável opcional (aba *Variables*): `SITE_URL`, endereço público do site. Padrão: `https://maua360.com.br`.

## Como tirar os dados da Meta

1. Em https://developers.facebook.com/apps crie um app do tipo **Empresa** (ex.: "Mauá 360 Publicador").
2. Abra o **Explorador da API do Graph** (https://developers.facebook.com/tools/explorer), escolha o app e clique em **Gerar token de acesso** com as permissões: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`, `business_management`. Autorize a página Mauá 360 e o Instagram @portalmaua360.
3. Copie o token, cole no **Depurador de token** (https://developers.facebook.com/tools/debug/accesstoken) e clique em **Estender token de acesso**. Copie o token novo (vale 60 dias).
4. De volta ao Explorador, cole o token novo e consulte `me/accounts`. Na resposta, a página Mauá 360 traz `id` (= `META_PAGE_ID`) e `access_token` (= `META_PAGE_TOKEN`, não expira).
5. Consulte `<META_PAGE_ID>?fields=instagram_business_account`. O `id` que aparece é o `META_IG_USER_ID`.
6. Cadastre os três como segredos no GitHub.

O app pode ficar em modo de desenvolvimento: como você é administrador do app e da página, não precisa de revisão da Meta para postar nas suas próprias contas.

## Limites

- Instagram: até 100 posts por API a cada 24 horas; só JPEG; link na legenda não é clicável.
- Se você trocar a senha do Facebook ou remover o app, o token da página deixa de valer: gere outro (passos 2 a 5).
- Para repostar uma matéria: Actions > Redes sociais > Run workflow, informando o slug.

## Foto sua (do evento)

1. No app do GitHub, abra o PR da matéria.
2. Escreva um comentário, toque no ícone de imagem e anexe a foto. Se quiser crédito, escreva na linha de baixo: `Foto: Nome do fotógrafo` (sem isso, sai "Foto: Mauá 360").
3. Envie o comentário e depois clique em **Merge**.

Vale a foto do comentário mais recente. Só contam comentários de quem tem acesso ao repositório.
