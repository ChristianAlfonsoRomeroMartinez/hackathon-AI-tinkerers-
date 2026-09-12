# Inyección de snapshot WIP — notas de auditoría

Script: `scripts/inject_wip_snapshot.py`, semilla determinista `20260912`.

El dataset original resuelve el 100% de los 6.000 tickets (no hay WIP).
Para demostrar la funcionalidad de aging de WIP en vivo, se congeló el
historial de **45 tickets** (0.75% del total)
en un estado que realmente visitaron, descartando sus eventos posteriores
(incluida la eventual resolución). No se inventaron transiciones nuevas:
solo se recortó el historial real en un punto real.

Conteo objetivo por estado (calibrado con Ley de Little sobre las medias
de `get_state_queue_times()`):

- Pending Approval Security: objetivo 15, aplicado 15
- In Progress: objetivo 14, aplicado 14
- Backlog: objetivo 5, aplicado 5
- Triage: objetivo 5, aplicado 5
- In Review: objetivo 3, aplicado 3
- Waiting Handoff: objetivo 2, aplicado 2
- Reopened: objetivo 1, aplicado 1

De estos, 2 son casos de
abandono deliberadamente antiguo (creados hace mucho, aún abiertos) para dar
evidencia narrativa de negligencia extrema, no solo el patrón agregado.

Impacto sobre la calibración de las 7 patologías (`ground_truth.json`):
marginal — 45/6000 tickets (0.75%) pasaron
de 'resuelto' a 'abierto', sin alterar categoría, equipo declarado, ni los
flags precalculados de patología (is_hidden_operational_debt, hero_involved,
hero_absence_hit, is_cross_team_flow) en tickets.csv.

## Tickets afectados

| ticket_id | estado congelado | congelado en | creado | caso de abandono |
|---|---|---|---|---|
| TCK-01378 | Backlog | 2026-09-01T18:46:47.122552 | 2026-09-01T18:46:47.122552 | no |
| TCK-01218 | Backlog | 2026-09-01T09:35:35.167985 | 2026-09-01T09:35:35.167985 | no |
| TCK-02508 | Backlog | 2026-08-31T05:06:43.233724 | 2026-08-31T05:06:43.233724 | no |
| TCK-02670 | Backlog | 2026-09-06T01:21:44.526482 | 2026-09-06T01:21:44.526482 | no |
| TCK-03567 | Backlog | 2026-08-30T12:43:38.591292 | 2026-08-30T12:43:38.591292 | no |
| TCK-05926 | In Progress | 2026-08-28T12:17:13.545731 | 2026-08-24T16:47:43.488562 | no |
| TCK-00627 | In Progress | 2026-09-01T18:22:15.209120 | 2026-09-01T03:36:30.638272 | no |
| TCK-03408 | In Progress | 2026-09-06T23:38:23.174316 | 2026-09-06T09:02:22.811470 | no |
| TCK-05424 | In Progress | 2026-08-31T09:10:17.012386 | 2026-08-26T21:29:04.387215 | no |
| TCK-05142 | In Progress | 2026-08-28T10:08:08.971054 | 2026-08-28T04:21:12.783114 | no |
| TCK-00519 | In Progress | 2026-09-07T07:32:09.494560 | 2026-09-07T00:52:49.264903 | no |
| TCK-04570 | In Progress | 2026-08-27T13:32:55.378760 | 2026-08-26T06:20:58.703049 | no |
| TCK-05289 | In Progress | 2026-09-06T20:48:09.980047 | 2026-09-06T06:13:26.174261 | no |
| TCK-01178 | In Progress | 2026-09-05T02:57:34.558849 | 2026-09-04T05:51:16.168101 | no |
| TCK-04845 | In Progress | 2026-09-03T12:11:41.308377 | 2026-09-02T21:40:16.811186 | no |
| TCK-04491 | In Progress | 2026-08-25T01:31:13.046807 | 2026-08-24T21:53:16.832217 | no |
| TCK-00683 | In Progress | 2026-09-04T06:11:31.014883 | 2026-09-03T21:30:09.028182 | no |
| TCK-01497 | In Progress | 2026-08-26T23:30:17.043281 | 2026-08-26T10:06:25.873953 | no |
| TCK-02355 | In Progress | 2026-08-30T19:10:46.977470 | 2026-08-30T04:49:21.006280 | no |
| TCK-02419 | In Review | 2026-09-03T13:43:54.103809 | 2026-09-02T02:50:06.480557 | no |
| TCK-04644 | In Review | 2026-08-29T23:30:35.100970 | 2026-08-29T08:08:48.694523 | no |
| TCK-01249 | In Review | 2026-08-31T17:07:30.707901 | 2026-08-31T01:56:53.204899 | no |
| TCK-02869 | Pending Approval Security | 2025-12-18T12:23:17.935103 | 2025-12-18T05:53:50.239831 | sí |
| TCK-00413 | Pending Approval Security | 2026-01-16T03:04:02.232117 | 2026-01-15T08:46:16.638633 | sí |
| TCK-04098 | Pending Approval Security | 2026-08-31T08:52:14.569895 | 2026-08-30T21:17:32.431372 | no |
| TCK-01839 | Pending Approval Security | 2026-09-01T16:50:13.890370 | 2026-08-31T09:37:18.791589 | no |
| TCK-01048 | Pending Approval Security | 2026-09-07T04:09:39.701450 | 2026-09-06T04:45:06.575785 | no |
| TCK-00378 | Pending Approval Security | 2026-09-07T02:00:40.055195 | 2026-09-06T13:44:56.165911 | no |
| TCK-04217 | Pending Approval Security | 2026-08-30T12:50:31.567873 | 2026-08-28T04:32:37.744303 | no |
| TCK-01009 | Pending Approval Security | 2026-08-25T11:43:41.073790 | 2026-08-24T23:44:35.177857 | no |
| TCK-04335 | Pending Approval Security | 2026-08-29T10:33:38.205465 | 2026-08-28T11:45:20.661697 | no |
| TCK-03421 | Pending Approval Security | 2026-08-29T04:01:51.270827 | 2026-08-27T16:41:19.862508 | no |
| TCK-01005 | Pending Approval Security | 2026-09-01T00:18:22.188009 | 2026-08-30T22:58:34.967087 | no |
| TCK-02709 | Pending Approval Security | 2026-09-01T02:48:41.112439 | 2026-08-31T04:18:01.026328 | no |
| TCK-04780 | Pending Approval Security | 2026-08-31T12:30:57.096968 | 2026-08-30T22:19:48.934106 | no |
| TCK-02969 | Pending Approval Security | 2026-08-30T06:33:35.549624 | 2026-08-29T22:09:23.969331 | no |
| TCK-04281 | Pending Approval Security | 2026-09-02T17:09:41.223177 | 2026-09-02T04:57:21.251932 | no |
| TCK-00712 | Reopened | 2026-08-31T19:39:03.402534 | 2026-08-28T08:22:40.321993 | no |
| TCK-01308 | Triage | 2026-08-26T05:52:13.332531 | 2026-08-25T20:21:59.871937 | no |
| TCK-02854 | Triage | 2026-09-02T14:28:47.354352 | 2026-09-02T03:50:18.535892 | no |
| TCK-01147 | Triage | 2026-08-31T17:13:06.620288 | 2026-08-29T11:18:07.829941 | no |
| TCK-00756 | Triage | 2026-09-02T00:57:26.397887 | 2026-09-01T04:34:39.406625 | no |
| TCK-01332 | Triage | 2026-09-01T13:34:04.216427 | 2026-09-01T13:00:55.542148 | no |
| TCK-05787 | Waiting Handoff | 2026-08-27T19:20:20.955913 | 2026-08-24T18:13:06.241402 | no |
| TCK-05843 | Waiting Handoff | 2026-08-30T19:17:59.823568 | 2026-08-27T15:12:18.155772 | no |
