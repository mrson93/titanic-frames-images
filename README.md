# titanic-frames-images

Frames ainda necessários do Titanic (1997), 1 por segundo, com legenda
queimada. São servidos por `raw.githubusercontent.com` para o
[titanic-frames-bot](https://github.com/mrson93/titanic-frames-bot).

Todos os dias, às 09:07 no horário de São Paulo, o workflow
`prune-posted-frames` remove os frames publicados até 23:59 do dia anterior e
recria o `main` como um novo commit raiz. A lista de preservação vem do
`manifest.json` e do histórico de `state.json` do bot; se qualquer frame futuro
estiver ausente, a limpeza é abortada antes do force-push.

Como o histórico é reescrito diariamente, clones antigos deste repositório não
devem fazer push de volta para o `main`.
