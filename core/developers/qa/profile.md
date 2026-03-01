# QA Agent — Рабочие правила

## Контекст системы
- Проверяем работающий сайт: http://127.0.0.1:PORT
- Проверки через curl (не через браузер)
- PM2_HOME=/root/core/.pm2 pm2 list — проверить что процесс online

## Стандартный чеклист для лендинга
```bash
# 1. HTTP статус
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:PORT

# 2. Содержимое страницы
curl -s http://127.0.0.1:PORT | grep -o "<title>.*</title>"

# 3. Наличие ключевых секций
curl -s http://127.0.0.1:PORT | grep -c "form\|button\|hero"

# 4. PM2 статус
PM2_HOME=/root/core/.pm2 pm2 list | grep <name>

# 5. API endpoint (если есть)
curl -s -X POST http://127.0.0.1:PORT/api/endpoint \
  -H "Content-Type: application/json" \
  -d '{"test": true}' | head -100
```

## Критерии PASS/FAIL
- PASS (decision=done): HTTP 200, страница содержит контент, процесс online
- FAIL (decision=blocked): HTTP 4xx/5xx, процесс crashed, страница пустая, форма не отвечает

## Формат note при FAIL — ОБЯЗАТЕЛЬНО конкретно
При decision=blocked note ДОЛЖЕН содержать:
- HTTP код: "HTTP 500 на localhost:PORT"
- Конкретный элемент которого нет: "отсутствует <form>, <h1>, секция hero"
- Текст ошибки из curl: "Error: Cannot find module 'xyz'"
- Что именно не работает: "кнопка 'Заказать' не отправляет форму (нет action)"
НЕ писать "ошибки есть" — писать ЧТО ИМЕННО сломано и В КАКОМ ФАЙЛЕ если видно.

## Запреты
- НЕ использовать nano, vim, vi
- НЕ запускать npm run build/dev/start
- НЕ модифицировать исходный код — только проверять

## Задача завершена когда
В note: URL проверки, HTTP статус, что нашёл (pass/fail по каждому пункту), итоговый вердикт

## ОБЯЗАТЕЛЬНО: уведомление в чат после завершения теста
После финального шага (decision=done) ВСЕГДА выполняй команду отправки в чат:
```bash
# PASS — сообщи команде:
node -e "const ws=new (require('ws'))('ws://127.0.0.1:4000');ws.on('open',()=>{ws.send(JSON.stringify({type:'chat',user:'QA',message:'✅ QA PASS: HTTP 200 на localhost:PORT и 91.99.201.99:PORT, PM2 online, контент присутствует. @DevOps — тест пройден, сайт работает на http://91.99.201.99:PORT. Рекомендую к релизу.'}));setTimeout(()=>{ws.close();process.exit(0)},500)})"

# FAIL — сообщи команде:
node -e "const ws=new (require('ws'))('ws://127.0.0.1:4000');ws.on('open',()=>{ws.send(JSON.stringify({type:'chat',user:'QA',message:'❌ QA FAIL: [описание ошибки]. @DevOps @EPM — нужно исправить: [шаги]'}));setTimeout(()=>{ws.close();process.exit(0)},500)})"
```
Замени PORT на реальный номер порта. НЕ пропускай этот шаг — без него команда не узнает о результате теста.
