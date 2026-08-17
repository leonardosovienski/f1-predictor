# Validação local — 2026-08-17

## Escopo

Validação do hardening do gate por estratégia e da closure de dinheiro real no
commit-base `f92c50b`, sem alteração de evidência científica ou abertura de
trilhas.

## Resultado do domínio

- testes direcionados de betting, closure e aprovação manual: verdes;
- Ruff: verde;
- Pyright: verde;
- hashes preservados da closure: válidos;
- `f1/h2h-post-qualifying/v1`: ausente do registro e `NO-GO`;
- `f1/winner-pre-event/v1`: registrado, mas `NO-GO` por H1-F1 refutada;
- `real_money_operation`: continua `PERMANENTLY_BLOCKED`.

## Intermitência externa do scheduler

A suíte integral pode falhar em
`test_portable_scheduler_success_heartbeat_and_terminal_failure`. O artefato
terminal reproduzido registrou:

```text
[WinError 5] Access is denied: .heartbeat.json.<uuid>.tmp -> heartbeat.json
```

O erro ocorre dentro de `predictor_ops 3.0.0` durante a substituição atômica do
heartbeat no Windows. O mesmo job também foi executado com sucesso fora da
suíte, confirmando natureza intermitente. `predictor_ops` classifica o `OSError`
como `CONFIGURATION_ERROR` e não tenta novamente o `os.replace`.

Não foi aplicado workaround em `f1-predictor`: aumentar intervalos, aceitar
`CONFIGURATION_ERROR` ou repetir o teste no consumidor mascararia a garantia
operacional. A correção pertence a `predictor_ops` e deve adicionar retry
limitado para falhas transitórias de replace, preservando falha fechada para
erros persistentes, seguido de nova release da wheel.
