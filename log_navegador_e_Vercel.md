[ClientPersistence] Voltou do background, mantendo estado.
VM561 0z~b7b0h9~.b9.js:1  GET https://consultoria-empresarial-v2.vercel.app/api/projects/242f5d9a-374b-4946-a07c-080fbf435b6a/documents 500 (Internal Server Error)
(anônimo) @ VM561 0z~b7b0h9~.b9.js:1
iv @ 00ilazh50sdzh.js:1
ud @ 00ilazh50sdzh.js:1
up @ 00ilazh50sdzh.js:1
sx @ 00ilazh50sdzh.js:1
(anônimo) @ 00ilazh50sdzh.js:1
O @ 00ilazh50sdzh.js:1Entenda o erro
VM561 0z~b7b0h9~.b9.js:1 [LiveKit] AudioContext desbloqueado com sucesso.
VM561 0z~b7b0h9~.b9.js:1 [Room] Conectado com sucesso.
VM561 0z~b7b0h9~.b9.js:1 publishing track {room: 'mentoria-242f5d9a-374b-4946-a07c-080fbf435b6a', roomID: '', participant: 'user-f6e6c76a-e2af-4426-8eb1-c29a87e81220', pID: 'PA_o4PRonv2wwQW', trackID: undefined, …}
VM561 0z~b7b0h9~.b9.js:1 [LiveKit] Microfone ativado com sucesso (tentativa 1).
VM561 0z~b7b0h9~.b9.js:1 [LiveKit] Analisador de áudio conectado.
5mentorship/242f5d9a-…a07c-080fbf435b6a:1 Uncaught (in promise) Error: A listener indicated an asynchronous response by returning true, but the message channel closed before a response was receivedEntenda o erro
0do_k5nmbrbbw.js:2 [ClientPersistence] Voltou do background, mantendo estado.
VM561 0z~b7b0h9~.b9.js:1 disconnect from room {room: 'mentoria-242f5d9a-374b-4946-a07c-080fbf435b6a', roomID: 'RM_ngtrRqD6Hifu', participant: 'user-f6e6c76a-e2af-4426-8eb1-c29a87e81220', pID: 'PA_o4PRonv2wwQW'}
VM561 0z~b7b0h9~.b9.js:1 [Room] Desconexão intencional.
dashboard:1 Uncaught (in promise) Error: A listener indicated an asynchronous response by returning true, but the message channel closed before a response was receivedEntenda o erro
0do_k5nmbrbbw.js:2 [ClientPersistence] Voltou do background, mantendo estado.



LOG vercel.

Apr 04 18:31:02.53
GET
200
consultoria-empresarial-v2.vercel.app
/mentorship/242f5d9a-374b-4946-a07c-080fbf435b6a
Apr 04 18:31:01.65
GET
200
consultoria-empresarial-v2.vercel.app
/mentorship/242f5d9a-374b-4946-a07c-080fbf435b6a
Apr 04 18:18:02.91
GET
304
consultoria-empresarial-v2.vercel.app
/
Apr 04 18:18:02.90
GET
304
consultoria-empresarial-v2.vercel.app
/
Apr 04 18:18:02.83
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard
Apr 04 18:18:02.82
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard
Apr 04 18:18:02.81
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/plans
Apr 04 18:18:02.75
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/plans
Apr 04 18:18:02.74
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/plans
Apr 04 18:18:02.72
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:18:02.71
GET
200
consultoria-empresarial-v2.vercel.app
/mentorship/242f5d9a-374b-4946-a07c-080fbf435b6a
Apr 04 18:18:02.68
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:18:02.67
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:18:02.61
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:18:02.61
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:18:02.60
GET
304
consultoria-empresarial-v2.vercel.app
/
Apr 04 18:18:02.51
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard
Apr 04 18:18:02.51
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/plans
Apr 04 18:18:02.50
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:18:02.50
GET
200
consultoria-empresarial-v2.vercel.app
/mentorship/242f5d9a-374b-4946-a07c-080fbf435b6a
Apr 04 18:18:02.08
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard
Apr 04 18:18:00.16
GET
200
consultoria-empresarial-v2.vercel.app
/api/dashboard
Apr 04 18:18:00.01
POST
200
consultoria-empresarial-v2.vercel.app
/api/sessions/finalize
Apr 04 18:17:59.63
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard
Apr 04 18:10:32.16
POST
200
consultoria-empresarial-v2.vercel.app
/api/livekit/token
Apr 04 18:10:30.88
GET
500
consultoria-empresarial-v2.vercel.app
/api/projects/242f5d9a-374b-4946-a07c-080fbf435b6a/documents
Erro ao listar documentos: Error: Failed query: select "id", "project_id", "file_name", "content", "created_at" from "project_documents" "projectDocuments" where "projectDocuments"."project_id" = $1 order by "projectDocuments"."created_at" desc params: 242f5d9a-374b-4946-a07c-080fbf435b6a at b.queryWithCache (.next/server/chunks/_12k7116._.js:24:39482) at async b.execute (.next/server/chunks/_12k7116._.js:24:42526) at async E (.next/server/chunks/[root-of-the-server]__0vglq30._.js:7:9215) at async h (.next/server/chunks/[root-of-the-server]__0vglq30._.js:7:12709) at async l (.next/server/chunks/[root-of-the-server]__0vglq30._.js:7:13750) at async Module.R [as handler] (.next/server/chunks/[root-of-the-server]__0vglq30._.js:7:14857) { query: 'select "id", "project_id", "file_name", "content", "created_at" from "project_documents" "projectDocuments" where "projectDocuments"."project_id" = $1 order by "projectDocuments"."created_at" desc', params: [ '242f5d9a-374b-4946-a07c-080fbf435b6a' ], [cause]: error: relation "project_documents" does not exist at <unknown> (.next/server/chunks/_12k7116._.js:9:28995) at async (.next/server/chunks/_12k7116._.js:24:42570) at async b.queryWithCache (.next/server/chunks/_12k7116._.js:24:39457) at async b.execute (.next/server/chunks/_12k7116._.js:24:42526) at async E (.next/server/chunks/[root-of-the-server]__0vglq30._.js:7:9215) at async h (.next/server/chunks/[root-of-the-server]__0vglq30._.js:7:12709) { length: 116, severity: 'ERROR', code: '42P01', detail: undefined, hint: undefined, position: '70', internalPosition: undefined, internalQuery: undefined, where: undefined, schema: undefined, table: undefined, column: undefined, dataType: undefined, constraint: undefined, file: 'parse_relation.c', line: '1449', routine: 'parserOpenTable' } }
Apr 04 18:10:30.87
POST
200
consultoria-empresarial-v2.vercel.app
/api/sessions
[Sessions API] Agent dispatch criado para a sala mentoria-242f5d9a-374b-4946-a07c-080fbf435b6a
Apr 04 18:10:30.37
GET
200
consultoria-empresarial-v2.vercel.app
/mentorship/242f5d9a-374b-4946-a07c-080fbf435b6a
Apr 04 18:10:28.90
GET
304
consultoria-empresarial-v2.vercel.app
/
Apr 04 18:10:28.89
GET
304
consultoria-empresarial-v2.vercel.app
/
Apr 04 18:10:28.83
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard
Apr 04 18:10:28.81
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard
Apr 04 18:10:28.81
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/plans
Apr 04 18:10:28.75
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/plans
Apr 04 18:10:28.72
GET
200
consultoria-empresarial-v2.vercel.app
/mentorship/242f5d9a-374b-4946-a07c-080fbf435b6a
Apr 04 18:10:28.58
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/plans
Apr 04 18:10:28.57
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:10:28.53
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:10:28.28
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:10:28.27
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:10:28.25
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription
Apr 04 18:10:28.18
GET
304
consultoria-empresarial-v2.vercel.app
/
Apr 04 18:10:28.16
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/plans
Apr 04 18:10:28.15
GET
304
consultoria-empresarial-v2.vercel.app
/dashboard/subscription