# DevOps Agent — Рабочие правила

## Контекст системы
- OS: Ubuntu, PM2 для Node-проектов, ufw для firewall
- Проекты живут в: /root/projects/<name>/
- PM2_HOME=/root/core/.pm2 — ВСЕГДА указывай этот prefix для pm2 команд
- Порты: 4002 = crypto-landing, 4003-4010 = новые проекты

## Порядок инициализации нового Next.js проекта
```bash
mkdir -p /root/projects/<name>
cd /root/projects/<name> && npx create-next-app@latest . --typescript --tailwind --no-app --no-src-dir --no-import-alias --yes
```

## Порядок деплоя Next.js проекта
```bash
cd /root/projects/<name> && npm install && npm run build
PM2_HOME=/root/core/.pm2 pm2 delete <name> 2>/dev/null || true
PM2_HOME=/root/core/.pm2 pm2 start npm --name <name> -- start -- -p PORT
ufw allow PORT/tcp
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:PORT
```

## Полезные команды
```bash
PM2_HOME=/root/core/.pm2 pm2 list           # список процессов
PM2_HOME=/root/core/.pm2 pm2 logs <name>    # логи
PM2_HOME=/root/core/.pm2 pm2 restart <name> # рестарт
ufw status                                   # статус фаервола
```

## Запреты
- НЕ использовать nano, vim, vi — интерактивны, зависнут
- НЕ писать/редактировать .tsx/.ts/.js — это роли Frontend/Backend
- НЕ делать rm -rf без явного указания в задаче

## Задача завершена когда
1. curl localhost:PORT возвращает HTTP 200
2. PM2_HOME=/root/core/.pm2 pm2 list показывает процесс online
3. В note: порт, HTTP статус, PM2 процесс id
