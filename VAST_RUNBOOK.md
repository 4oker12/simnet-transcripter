# SIMNET Transcriber: эксплуатация и восстановление на Vast.ai

## Назначение и устройство

SIMNET Transcriber принимает аудио через FastAPI и транскрибирует его с помощью
faster-whisper. Профили `baseline` и `simnet` используют одну модель; профиль
`simnet` добавляет предметный словарь. Инференс сериализован в приложении.
Архитектура: Supervisor → `/venv/main/bin/python` / Uvicorn / FastAPI →
faster-whisper → CTranslate2 → CUDA → NVIDIA GeForce RTX 3090 (24 GiB).

Instance: 51907746. Проект: `/workspace/simnet-transcriber`.
Окружение: `/venv/main`, Python 3.12.14.
Репозиторий: https://github.com/4oker12/simnet-transcripter.git.
Исходный HEAD ремонта: `504005d` (ветка `main`).
Ветка сохранения восстановления: `fix/vast-rtx3090-transcriber-recovery`.
Модель, recovery logs, резервные копии и аудио остаются только на instance;
в Git сохраняются исходники, конфигурация и эта инструкция.

Перед любыми работами полностью прочитать:

```bash
cat /etc/vast-agents-guide.md
vast-capabilities metrics,packages
```

Не публиковать вывод окружения, командные строки всех процессов, токены или ключи.
`/workspace` на этом instance **не является volume**: stop/start сохраняет данные,
recycle/destroy их уничтожает. Для сохранения за пределами instance нужна отдельная
резервная копия в согласованное пользователем хранилище.

## Конфигурация

* Supervisor: `/workspace/simnet-transcriber/simnet-supervisord.conf`.
* Программа: `/workspace/simnet-transcriber/simnet-transcriber.conf`.
* Launcher: `/workspace/simnet-transcriber/simnet-transcriber-supervisor.sh`.
* Socket: `/tmp/simnet-transcriber-supervisor.sock`, mode 0700.
* PID daemon: `/tmp/simnet-transcriber-supervisord.pid`.
* Профили: `/workspace/simnet-transcriber/config/asr_profiles.json`.
* Модель: `/workspace/simnet-transcriber/models/faster-whisper-large-v3`.
* Model ID: `Systran/faster-whisper-large-v3`, формат CTranslate2.
* Revision: `edaa852ec7e145841d8ffdb056a99866b5f0a478`.
* API: исключительно `127.0.0.1:8000`.

Supervisor задаёт `PROC_NAME=simnet-transcriber`,
`SIMNET_MODEL_PATH=/workspace/simnet-transcriber/models/faster-whisper-large-v3`,
`HF_HUB_DISABLE_XET=1`, `HF_HUB_OFFLINE=1`.
`model=large-v3`, `device=cuda`, `compute_type=float16` заданы в обоих профилях.
`SIMNET_MODEL_PATH` отделяет физический каталог от публичного имени модели;
при его наличии приложение использует `local_files_only=True`.
Launcher запускает:

```bash
cd /workspace/simnet-transcriber
/venv/main/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Это описание команды, для эксплуатации запускать через Supervisor ниже.
`autostart=false`, `autorestart=unexpected`: после запуска самого daemon программу
нужно явно запустить; падение уже запущенной программы вызывает её перезапуск.
`SIMNET_START_TIMEOUT_SECONDS` задаёт таймаут `start.sh` (по умолчанию 600 секунд).
Для скачивания нужны `HF_HUB_OFFLINE=0`, `HF_HUB_DISABLE_XET=1`,
`HF_HUB_DOWNLOAD_TIMEOUT=60`, `HF_HUB_ETAG_TIMEOUT=30`; downloader устанавливает их сам.

## Управление

Всегда указывать проектный config. Системный Supervisor Vast обслуживает другие
программы; его не останавливать. Не запускать второй проектный daemon.

```bash
# Проверить daemon и программу
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf pid
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf status
# Запустить
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf start simnet-transcriber
# Остановить только программу
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf stop simnet-transcriber
# Перезапустить
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf restart simnet-transcriber
# После изменения конфигурации
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf reread
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf update
```

`stop.sh` также завершает проектный daemon и удаляет его socket/PID; для обычного
останова использовать команду `supervisorctl stop` выше.
`bootstrap-vast.sh` устанавливает зависимости и может стартовать daemon; не нужен
для обычного рестарта. Пользовательские изменения этого файла при ремонте сохранены.

Логи stdout и stderr объединены в `/tmp/simnet-transcriber.log`, ротация 10 MiB × 2.
Приложение дополнительно пишет `/workspace/simnet-transcriber/logs/server.log`.
Лог daemon: `/tmp/simnet-transcriber-supervisord.log`.

```bash
tail -n 100 /tmp/simnet-transcriber.log
tail -n 100 /workspace/simnet-transcriber/logs/server.log
tail -n 100 /tmp/simnet-transcriber-supervisord.log
ss -lntp 'sport = :8000'
curl --max-time 10 -i http://127.0.0.1:8000/health
curl --max-time 10 -fsS http://127.0.0.1:8000/health | jq .
```

Ограниченное ожидание готовности:

```bash
cd /workspace/simnet-transcriber
SIMNET_START_TIMEOUT_SECONDS=180 ./start.sh
```

## GPU, CUDA и пакеты

```bash
nvidia-smi
nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
/venv/main/bin/python -m pip show torch torchvision faster-whisper ctranslate2 huggingface-hub
/venv/main/bin/python - <<'PY'
import torch, torchvision, ctranslate2
print('torch:', torch.__version__, 'torchvision:', torchvision.__version__)
print('CUDA runtime:', torch.version.cuda, 'available:', torch.cuda.is_available())
print('GPU:', torch.cuda.get_device_name(0))
print('CUDA operation:', torch.ones(1, device='cuda').sum().item())
print('CTranslate2:', ctranslate2.__version__)
print('Supported compute types:', ctranslate2.get_supported_compute_types('cuda'))
PY
```

Фактические версии ремонта: faster-whisper 1.2.1, CTranslate2 4.8.2,
huggingface-hub 1.30.0, torch 2.11.0+cu128, torchvision 0.26.0+cu128.
Драйвер 580.142 поддерживает CUDA до 13.0; toolkit и runtime torch — 12.8.
Это разные версии разных компонентов, не повод обновлять драйвер.

## Целостность модели

Каталог содержит обычные файлы, не ссылки на Hub snapshot. Размеры в байтах:

| Файл | Размер |
|---|---:|
| model.bin | 3087284237 |
| config.json | 2394 |
| tokenizer.json | 2480617 |
| vocabulary.json | 1068114 |
| preprocessor_config.json | 340 |
| README.md | 2052 |
| .gitattributes | 1519 |

SHA-256 `model.bin`:
`69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1`.
`verify_model.py` проверяет размеры, SHA-256 весов, Git blob SHA-1 остальных файлов,
JSON, читаемость, отсутствие symlinks и incomplete. Значения взяты из HF manifest
указанной revision, сохранённого в `logs/recovery-20260921/manifest.json`.

```bash
/venv/main/bin/python /workspace/simnet-transcriber/scripts/verify_model.py
du -sh /workspace/simnet-transcriber/models/faster-whisper-large-v3
find /workspace/simnet-transcriber/models/faster-whisper-large-v3 -type f -printf '%p %s bytes\n'
find /workspace/simnet-transcriber/models -xtype l -print
find /workspace/simnet-transcriber/models -name '*.incomplete' -print
find /workspace/simnet-transcriber/models -name '*.lock' -print
```

Нулевой `.lock` сам по себе не свидетельствует о повреждении. Не удалять lock
живого downloader. `.cache/huggingface` внутри local_dir хранит метаданные
для повторной загрузки; наличие этого каталога нормально.

Отдельный smoke test выполнять с остановленным сервисом, чтобы не грузить две копии:

```bash
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf stop simnet-transcriber
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_XET=1 /venv/main/bin/python - <<'PY'
from faster_whisper import WhisperModel
import numpy as np
m = WhisperModel('/workspace/simnet-transcriber/models/faster-whisper-large-v3',
                 device='cuda', compute_type='float16', local_files_only=True)
print(m.model.device, m.model.compute_type)
assert m.model.device == 'cuda' and m.model.compute_type == 'float16'
segments, info = m.transcribe(np.zeros(16000, dtype=np.float32), language='ru',
                              vad_filter=False, beam_size=1)
print('Inference OK:', list(segments))
PY
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf start simnet-transcriber
```

## Безопасная повторная загрузка без Xet

Сначала остановить сервис, проверить PID и отсутствие downloader. Сохранить
исходный список файлов, размеры и hashes; не удалять рабочую модель из-за сетевой
ошибки. Перед заменой доказанно повреждённого файла сохранить его отдельно, если
позволяет место. Downloader ограничивает число попыток четырьмя, использует
официальный `snapshot_download`, явный local_dir, HTTP и закреплённую revision.
Для ограничения общего времени используется `timeout`:

```bash
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf stop simnet-transcriber
ss -lntp 'sport = :8000'
df -h /workspace
df -i /workspace
cd /workspace/simnet-transcriber
timeout --signal=TERM --kill-after=30s 2h /venv/main/bin/python -u scripts/download_model.py
/venv/main/bin/python scripts/verify_model.py
```

При hash mismatch существующий неверный файл не перезаписывается автоматически:
остановить все его читатели/писатели, вывести точный путь, сохранить/удалить только
подтверждённый повреждённый файл и повторить downloader. Не запускать сервис до
успешного verify и CUDA smoke test.

При зависании определить файл по росту размера `.incomplete` и журналу. Проверить:

```bash
find /workspace/simnet-transcriber/models/faster-whisper-large-v3 -name '*.incomplete' -printf '%p %s bytes\n'
curl -fsS --connect-timeout 15 --max-time 30 -o /dev/null -w 'HTTP %{http_code}\n' https://huggingface.co/api/models/Systran/faster-whisper-large-v3
ps -eo pid,ppid,etime,comm
```

Не выводить signed redirect URLs или окружение с токенами. Прогресс может быть
медленным без зависания; сравнить размер с интервалом 30–60 секунд. Если процесс
перестал продвигаться, установить его PID/родителя и завершить TERM именно его.
После завершения проверять incomplete и повторять HTTP-загрузку. При проблеме
backend допустим HTTP Range download по manifest с правильной структурой,
проверкой Content-Range и итогового SHA-256; готовые веса принимать только после
`verify_model.py`. Пакет hf-xet удалять не требуется.

## Диагностика неисправностей

* **CUDA error:** проверить реальную CUDA-операцию выше и traceback. `nvidia-smi`
  без CUDA-операции недостаточен. При отсутствующих cuBLAS/cuDNN проверить
  `ldconfig -p | grep -E 'cublas|cudnn'` и библиотеки в `/venv/main`.
  Устанавливать только доказанно отсутствующий совместимый runtime в существующее
  окружение. Не устанавливать `cuda`, `cuda-drivers`, `nvidia-driver-*`, `libcuda*`;
  host driver менять нельзя. Не включать forward compatibility на RTX 3090.
* **FATAL/BACKOFF:** прочитать оба лога, проверить command, cwd, исполняемость
  launcher, путь `/venv/main/bin/python`, JSON профилей, model path и hash.
  Исправить причину, выполнить reread/update при изменении config, затем один
  осмысленный start. Не перезапускать бесконечно.
* **RUNNING без порта:** это живой процесс до завершения FastAPI lifespan.
  Искать `Model loaded successfully`, проверить VRAM, локальный путь и
  `HF_HUB_OFFLINE=1`; не ждать сетевую загрузку внутри API. Таймаут 180 секунд
  достаточен для диагностики; если истёк, читать логи, а не повторять рестарты.
* **Порт есть, health не отвечает:** использовать curl с max-time, сверить PID
  слушателя с Supervisor, посмотреть traceback/нагрузку и `config/asr_profiles.json`.
  Не завершать чужой процесс из-за одного занятого порта.
* **CPU вместо CUDA:** проверить оба профиля и настройки runtime; должны быть
  `cuda`/`float16`. Повторить отдельный smoke test и проверить GPU PID. Поле
  `gpu` в health само по себе лишь результат nvidia-smi, поэтому нужна VRAM.
* **Недостаточно VRAM:** получить GPU PID, исключить вторую копию модели и
  параллельный smoke test. Останавливать только установленный собственный процесс.
  Не переключать на CPU/int8: это нарушит требуемый режим.
* **Недостаточно диска/inode:** использовать `df -h`, `df -i`, `du -sh`.
  Для модели нужно около 3.1 GB плюс запас; при сохранении старой копии — ещё
  столько же. Чистить только конкретные подтверждённые incomplete/temporary файлы
  остановленной загрузки. Не удалять `/workspace`, проект, `/venv/main`, рабочие
  модели, аудио, результаты, секреты и данные Workbench.

Перед изменением любого файла сохранить его исходное состояние и записать diff.
Перед удалением вывести точный список целей. Dangling symlink можно удалить
только после проверки её назначения и отсутствия живого downloader. Исправные
blobs и другие модели не трогать. Старый неполный Hub cache теперь не используется.
VPN, WireGuard, sing-box, туннели и внешнюю публикацию порта не настраивать.

## Воспроизведение на новом Vast instance

Использовать PyTorch image с `/venv/main`, доступной CUDA и достаточной VRAM/диском.
Сначала прочитать guide и проверить hardware, storage и Supervisor. Получить
восстановленные исходники из ветки восстановления. Если каталог проекта ещё
отсутствует:

```bash
cd /workspace
git clone --branch fix/vast-rtx3090-transcriber-recovery https://github.com/4oker12/simnet-transcripter.git simnet-transcriber
cd /workspace/simnet-transcriber
/venv/main/bin/python -m pip install -r requirements.txt
/venv/main/bin/python -m pip install 'ctranslate2==4.8.2' 'huggingface-hub==1.30.0'
command -v ffmpeg ffprobe supervisorctl supervisord curl jq
```

При отсутствующих системных командах установить только нужные пакеты
`ffmpeg supervisor curl jq git`; не запускать установку драйверов.
При clone указанной ветки восстановленные исходники уже находятся на месте.
Запустить downloader и verify, выполнить CUDA smoke test до старта API.
Если daemon уже есть, использовать его. Только когда команда `ctl pid` не работает,
проверить сохранённый PID, процессы `supervisord` и socket; если живого проектного
daemon нет и устаревшие PID/socket проверены, запустить:

```bash
supervisord -c /workspace/simnet-transcriber/simnet-supervisord.conf
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf reread
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf update
cd /workspace/simnet-transcriber
SIMNET_START_TIMEOUT_SECONDS=180 ./start.sh
```

Не добавлять API в `/etc/portal.yaml`; порт 8000 не должен публиковаться наружу.
Для восстановления без сохранённых правок в app.py требуется заменить источник
WhisperModel на `os.environ.get('SIMNET_MODEL_PATH', state.model_name)` и включить
local_files_only при заданном пути; точный diff сохранён в журнале ремонта.

## Контрольный чек-лист

1. Supervisor RUNNING, PID соответствует Uvicorn из `/venv/main`.
2. `ss` показывает только `127.0.0.1:8000`.
3. Health HTTP 200, `ok=true`, `large-v3`, `cuda`, `float16`, RTX 3090.
4. Отдельный smoke test подтверждает фактический CUDA/float16 и inference.
5. nvidia-smi показывает процесс модели и VRAM.
6. После старта есть `Model loaded successfully`, нет фатального traceback.
7. verify прошёл, incomplete и dangling symlinks отсутствуют.
8. Runbook и журнал ремонта сохранены; внешние сервисы не изменены.

## Журнал ремонта

Исходные файлы: `logs/recovery-20260921/original/`.
Manifest: `logs/recovery-20260921/manifest.json`.
Удаления: `logs/recovery-20260921/deleted.txt`.
Причина: приложение загружало model ID при startup; Xet/Hub загрузка не завершила
model.bin. Процесс 7770 оставался RUNNING более часа до bind, VRAM была 0 MiB.
В кэше обнаружен incomplete 188743680 байт при ожидаемых 3087284237 байт;
существовали недоступные directory entries model.bin и его blob. Исправные малые
blobs сохранены. Удалён только incomplete; недоступные entries уже отсутствовали
при unlink. Для production введён обычный локальный каталог и offline startup.

### Дополнения по фактическому восстановлению

Из-за низкой скорости одного HTTP-потока применён
`scripts/download_model_http.py`: 12 потоков, диапазоны по 32 MiB, проверка HTTP 206,
точного Content-Range, размера каждого блока и SHA-256 собранного model.bin.
Повторный запуск использует готовые `.http-parts/*.part`; после финальной проверки
эти временные части можно удалить по точному списку. Общий запас места при сборке
нужен примерно 6.2 GB (части плюс готовый файл).

```bash
supervisorctl -c /workspace/simnet-transcriber/simnet-supervisord.conf stop simnet-transcriber
cd /workspace/simnet-transcriber
PYTHONPYCACHEPREFIX=/tmp/simnet-pycache timeout --signal=TERM --kill-after=30s 2h /venv/main/bin/python -u scripts/download_model_http.py
/venv/main/bin/python scripts/verify_model.py
```

Одновременно запускать только один downloader. Оба ремонтных скрипта используют
`/tmp/simnet-model-recovery.lock`. Это advisory lock: он не блокирует сторонние
HF CLI, поэтому сначала проверить процессы.

Дополнительная переменная Supervisor: `PYTHONPYCACHEPREFIX=/tmp/simnet-pycache`.
Она обходит обнаруженный ESTALE при атомарной записи старого
`__pycache__/app.cpython-312.pyc`. Старый кэш байткода не удалялся.

Старый неполный каталог
`models/models--Systran--faster-whisper-large-v3` сохранён целиком как
`logs/recovery-20260921/old-incomplete-hub-cache`.
В нём остались недоступные stale directory entries исходной файловой системы;
это архив диагностики, не рабочая модель. Не копировать его обратно в production.
Изменение только имени каталога сохранило исправные blobs и ссылки.

Старый `smoke_test.py` использует model ID и может снова инициировать Hub download.
Для проверки отремонтированного локального пути использовать inline smoke test
из этого runbook.

### Перенос исправлений на новый instance

На текущем instance можно создать пакет исходников, без моделей/секретов/аудио:

```bash
cd /workspace/simnet-transcriber
tar -czf /tmp/simnet-recovery-source.tar.gz app.py config/asr_profiles.json requirements.txt simnet-supervisord.conf simnet-transcriber.conf simnet-transcriber-supervisor.sh start.sh status.sh restart.sh scripts/verify_model.py scripts/download_model.py scripts/download_model_http.py VAST_RUNBOOK.md
```

Сохранить этот файл за пределами instance согласованным способом до recycle/destroy.
После доставки того же архива в `/tmp` нового instance и clone проекта:

```bash
cd /workspace/simnet-transcriber
tar -xzf /tmp/simnet-recovery-source.tar.gz
/venv/main/bin/python -m pip install -r requirements.txt
/venv/main/bin/python -m pip install 'ctranslate2==4.8.2' 'huggingface-hub==1.30.0'
PYTHONPYCACHEPREFIX=/tmp/simnet-pycache timeout --signal=TERM --kill-after=30s 2h /venv/main/bin/python -u scripts/download_model.py
/venv/main/bin/python scripts/verify_model.py
```

Далее выполнить CUDA smoke test, проверить отсутствие daemon-дубликата,
запустить проектный Supervisor и пройти весь чек-лист. Архив не создан и не
отправлен автоматически; команды описывают воспроизводимый перенос.

## Фактическое финальное состояние, 21 сентября 2026 UTC

Восстановление завершено. Supervisor daemon остался PID 2334; сервис RUNNING,
PID 14574. Модель в основном процессе загрузилась за 3.215 секунды.
`127.0.0.1:8000` слушает тот же PID; внешнего bind, port mapping 8000 и
portal reverse proxy для этого API нет. Системная конфигурация Vast не менялась.

Фактический HTTP 200 `/health`:

```json
{"ok":true,"model":"large-v3","device":"cuda","compute_type":"float16","gpu":"NVIDIA GeForce RTX 3090","default_profile":"simnet","busy":false,"waiting_requests":0}
```

GPU: NVIDIA GeForce RTX 3090, driver 580.142, driver CUDA 13.0;
VRAM 3881 / 24576 MiB, процесс `/venv/main/bin/python`, PID 14574,
3872 MiB по process query. Размер модели `du -sh`: 2.9G.
Веса и JSON прошли hash verification; incomplete=0, symlinks=0 в рабочей модели.
Отдельный CUDA/float16 smoke test с реальным decode прошёл (PID теста 14440
завершён до старта API). Тестовый POST `/transcribe` с секундой тишины вернул
HTTP 200, `ok=true`, пустой текст; это проверка pipeline, не качества ASR речи.
В журнале текущего запуска нет фатальной ошибки загрузки.

Созданы `VAST_RUNBOOK.md`, три скрипта в `scripts/`, локальная модель и журнал
`logs/recovery-20260921/`. Изменены только `app.py` (локальный источник модели)
и `simnet-transcriber.conf` (offline env и кэш Python). `bootstrap-vast.sh` уже
имел изменение прав доступа до ремонта; его байты совпадают с исходной копией.
Launcher и основной `simnet-supervisord.conf` не изменялись. Пакеты, драйвер,
Workbench, VPN и внешняя сеть не изменялись. Во время самого ремонта commit/push
не выполнялись; последующее сохранение исходников предусмотрено в отдельной
ветке `fix/vast-rtx3090-transcriber-recovery`, без merge в `main`.

Удалён исходный incomplete 188743680 байт, incomplete остановленной медленной
HTTP-попытки 157286400 байт; недоступные старые entries не удалось unlink,
они сохранены вместе со старым кэшем. После успешной проверки удалены созданные
ремонтом 93 временные части сборки (0000.part–0092.part); полный точный список
в `logs/recovery-20260921/temporary-parts-cleanup.txt`.

Полный итоговый вывод: `logs/recovery-20260921/final-verification.txt`.
Проверка согласованности PID/health/VRAM: `logs/recovery-20260921/acceptance.log`.
Список артефактов: `logs/recovery-20260921/artifacts.txt`.
Оставшиеся особенности: `/workspace` без постоянного volume; stale entries
сохранены только в архиве старого повреждённого кэша, старый `__pycache__`
обходится через PYTHONPYCACHEPREFIX. Новый рабочий каталог проходит проверки.
