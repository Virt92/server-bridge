
✅ [2026-03-01] Деплой обновленного esports-landing
→ Деплой esports-landing завершён успешно. npm run build прошёл без ошибок (Next.js 16, 3 страницы, 12с). PM2 process esports-landing (id=11) перезапущен → status=online. HTTP 200 на localhost:4004 и 91.99.201.99:4004. UFW порт 4004 уже был открыт.

✅ [2026-03-01] Инициализация проекта 3d-figures-landing
→ Проект 3d-figures-landing успешно инициализирован. create-next-app@latest создал скелет Next.js 16.1.6 + TypeScript + Tailwind в /root/projects/3d-figures-landing (pages router, no app, no src-dir, no eslint). npm install завершён: 48 пакетов установлено, 0 уязвимостей. Структура: pages/, styles/, p

✅ [2026-03-01] Деплой 3d-figures-landing
→ Деплой 3d-figures-landing завершён успешно. npm run build прошёл без ошибок (Next.js 16.1.6, 3 страницы, 29с). PM2 process 3d-figures-landing (id=12) запущен → status=online. HTTP 200 на localhost:4005 и 91.99.201.99:4005. UFW порт 4005 открыт.

✅ [2026-03-01] ПРАВИЛО: После успешного деплоя ВСЕГДА отправлять WebSocket уведомление: node -e "ws.send({user:'DevOps',message:'@EPM деплой PROJECT завершён, порт PORT доступен. @QA — начинай smoke-тест: http://91.99.201.99:PORT'})". Это запускает цепочку: DevOps→QA→EPM→Admin. Без этого цепочка уведомлений не работает.
