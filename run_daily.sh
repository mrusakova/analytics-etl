#!/bin/sh
# Ежедневный прогон загрузчика (вызывается из cron, см. README).
# Код берётся из уже собранного образа: после git pull нужен docker compose build.
cd "$(dirname "$0")" || exit 1

# Лог не растёт бесконечно: оставляем последние 3000 строк (~несколько месяцев).
[ -f etl.log ] && tail -n 3000 etl.log > etl.log.tmp && mv etl.log.tmp etl.log
exec >> etl.log 2>&1

echo "=== $(date '+%F %T') старт"
# flock -n: если вчерашний прогон почему-то ещё идёт — второй не запускаем.
flock -n /tmp/analytics-etl.lock docker compose run --rm etl
echo "=== $(date '+%F %T') конец, код $?"
