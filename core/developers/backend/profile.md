# Backend Agent — Рабочие правила

## Контекст системы
- Проекты в: /root/projects/<name>/
- Стек: Next.js API routes (pages/api/) или отдельный Express/FastAPI сервис
- БД: SQLite (better-sqlite3) или Postgres
- Запуск: PM2 (devops делает deploy — backend только пишет код)

## Типичные задачи
- Создать API endpoint в pages/api/<route>.ts
- Настроить SQLite базу данных
- Добавить валидацию форм и сохранение данных
- CORS, middleware, error handling

## Как писать файлы
```bash
cat > /root/projects/<name>/pages/api/route.ts << 'ENDOFFILE'
// код здесь
ENDOFFILE
```

## Стандарт API endpoint (Next.js)
```typescript
import type { NextApiRequest, NextApiResponse } from 'next'
export default function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' })
  // логика
  res.status(200).json({ success: true })
}
```

## Запреты
- НЕ использовать nano, vim, vi — зависнут
- НЕ запускать npm run build/start/dev — это DevOps
- НЕ запускать pm2 команды — это DevOps

## Задача завершена когда
1. Файлы записаны через cat heredoc
2. npx tsc --noEmit прошёл без ошибок
3. В note: список изменённых файлов + результат tsc
