# BrainScan — Спецификация режима разметки и Detect Actions

Контекст для Claude Code. Описывает полную логику UI и поведения трёх связанных режимов:
1. **Detect** — запуск автодетекции из Default State
2. **Detect Actions** — экран результатов с действиями Approve/Edit
3. **Annotate / Edit** — оверлей разметки

---

## Обзор

Режим разметки активируется двумя способами:

1. **Annotate** — из Default State виджета. Cold start или ручная разметка скриншота с нуля. Все поля пустые.
2. **Edit** — из Detect Actions после автодетекции. Поля Region и Tumor предзаполнены результатами моделей. Врач корректирует то, что считает неверным.

В обоих случаях открывается оверлей поверх всех окон с виджетом разметки внизу. Скриншот замораживается в момент открытия оверлея — последующие изменения на экране не влияют на разметку.

---

## Detect Actions: флоу автодетекции

### Запуск Detect

```
[Default State]
Click Detect
        ↓
Проверка статуса соединения:
    🟢 Connected            → продолжаем
    🔵 Syncing              → продолжаем (новый запрос ждёт)
    🟡 No connection        → кнопка задизейблена
    🟠 Model not deployed   → кнопка задизейблена
    🔴 Service unavailable  → кнопка задизейблена
        ↓
[Capturing...] — захват всех мониторов через mss
        ↓
INSERT screenshots (одна запись на сессию захвата)
сохранить все скриншоты → S3
        ↓
[Analyzing...] — отправка в локализатор
        ↓
Для каждого монитора параллельно:
    Локализатор обрабатывает скриншот
    INSERT localize_detections (одна запись на монитор)

    Если bbox найден:
        вырезать crop по bbox
        сохранить crop → S3
        INSERT localize_images
        Запустить детектор опухоли на crop'е
        INSERT tumor_detections

    Если bbox не найден:
        INSERT localize_detections с bbox=NULL
        crop и tumor_detections не создаются
        ↓
[Detect Actions] — показать результат
```

### UI Detect Actions

```
┌─────────────────────────────────────────┐
│ ← Back   ✓ Approve   ✎ Edit             │
└─────────────────────────────────────────┘
```

Только два действия: **Approve** и **Edit**. Кнопка Reject намеренно отсутствует — она бы дала только сигнал «модель не права», но не «где именно». Если врач не согласен с результатом, он идёт через Edit, где явно показывает что именно неверно.

### Approve — подтверждение результата модели

При нажатии Approve врач подтверждает **всё**: и локализацию (или её отсутствие), и детекцию опухоли (или её отсутствие).

### Edit — переход в режим коррекции

Открывается оверлей разметки с предзаполненными bbox/null от моделей. См. раздел «Вход через Edit (после автодетекции)» ниже.

---

## Состояния сущностей

Каждая из двух сущностей (Region и Tumor) находится в одном из трёх состояний:

| Состояние | Описание | Визуал в виджете |
|---|---|---|
| `empty` | Не задано | Кнопки `Add` и `Mark Null` активны |
| `bbox` | Нарисован bbox | Координаты `x, y, w, h` + кнопка `×` для сброса |
| `null` | Помечено как отсутствующее | Плашка `Null Region` / `Null Tumor` + `×` |

---

## Связь Region и Tumor

Опухоль не может существовать без области интереса. Это даёт каскадные правила:

```
Region = empty → Tumor: разрешены все состояния
Region = bbox  → Tumor: разрешены все состояния
Region = null  → Tumor: только null (автоматически)
                       Add Tumor задизейблен
                       Mark Null Tumor задизейблен
                       × у Tumor скрыт
                       Сбросить Tumor можно только через × у Region
```

### Каскадный сброс

При изменении Region:
- `× Region` (был bbox или null) → Region = empty, Tumor = empty
- `Mark Null` для Region → Region = null, Tumor = null (автоматически)

Это правило обеспечивает консистентность: ни в каком состоянии Tumor не может быть «осиротевшим» от Region.

---

## Доступность Send

```
Send активен когда:
    Region определён (bbox или null) И
    Tumor определён (bbox или null) И
    Нет невалидных bbox

Send задизейблен когда:
    Region = empty ИЛИ
    Tumor = empty ИЛИ
    Есть хотя бы один невалидный bbox
```

Это гарантирует что в БД попадает только полная и валидная разметка.

### Что считается невалидным bbox

- Tumor находится вне границ Region
- Bbox имеет нулевую или почти нулевую площадь (< 10×10 px)
- Tumor пересекается с другим Tumor (если применимо)

При невалидном bbox он подсвечивается красной обводкой на снимке. Соответствующая группа координат в виджете тоже подсвечивается красным. Врач должен исправить bbox перед Send.

**Никаких диалогов «расширить регион / обрезать опухоль» — простая семантика: Send задизейблен пока всё не валидно.**

---

## Мульти-bbox: несколько регионов и опухолей

В одном скриншоте может быть несколько регионов интереса (мульти-монитор или несколько окон вьювера) и несколько опухолей в одном регионе (метастазы).

### Поддержка в схеме БД

На один `screen_id` может быть несколько `localize_annotations` (с разными `monitor_index` или просто несколько областей на одном мониторе).
На один `localize_image_id` может быть несколько `tumor_annotations` (несколько опухолей в одном регионе).

### UI для мульти-bbox

Виджет показывает координаты всех bbox с группировкой:
- Группа Region: координаты каждого региона + крестик для удаления
- Группа Tumor: координаты каждой опухоли + крестик для удаления
- Навигация: стрелки `^` и `v` для перемещения по списку bbox, цифра показывает индекс активного

При большом количестве bbox в виджете отображаются только текущий выбранный + соседние, остальные сворачиваются.

### Подсветка связанных элементов

Двусторонняя связь между bbox на снимке и координатами в виджете:
- Ховер на bbox → подсвечивается соответствующая группа координат в виджете
- Ховер на группу координат в виджете → подсвечивается соответствующий bbox на снимке
- Клик на группу координат → bbox становится активным (его можно править, удалить, навигировать)

Это снижает когнитивную нагрузку при работе с несколькими bbox — врач видит какая координата какому bbox принадлежит.

---

## Появление кнопок Mark Null

`Mark Null` появляется в виджете **только когда соответствующие bbox полностью удалены**.

### Правило для Region

```
Есть хотя бы один Region bbox → видимы: Add Region, навигация по regions
Все Region bbox удалены       → видимы: Add Region, Mark Null Region
```

### Правило для Tumor

```
Есть хотя бы один Tumor bbox → видимы: Add Tumor, навигация по tumors
Все Tumor bbox удалены       → видимы: Add Tumor, Mark Null Tumor
```

Это решает все кейсы без перегруженного UI:

- **Кейс 5** (нет области, подтвердить): врач удаляет все Region bbox → появляется Mark Null Region → жмёт → Send
- **Кейс 3** (область есть, опухоли нет): врач оставляет Region, удаляет все Tumor → появляется Mark Null Tumor → жмёт → Send
- **Кейс 7** (cold start без опухоли): врач рисует Region, не рисует Tumor → Mark Null Tumor сразу доступна → жмёт → Send

### Каскадное правило

При активации `Mark Null Region`:
- Все Tumor bbox удаляются автоматически (опухоль не может существовать без региона)
- Tumor → null

Это раскрывает Mark Null Tumor (если он не был активен) и автоматически переводит Tumor в состояние null.

---

## Действия в UI

| Элемент | Эффект |
|---|---|
| `Add Region` | Активирует режим рисования bbox региона на оверлее. Курсор = crosshair. |
| `Mark Null` (Region) | Region → null. Tumor → null автоматически. |
| `Add Tumor` | Активирует режим рисования bbox опухоли. Доступен только при Region ≠ null. |
| `Mark Null` (Tumor) | Tumor → null. Доступен только при Region ≠ null. |
| `× Region` | Region → empty. Tumor → empty (каскадный сброс). |
| `× Tumor` | Tumor → empty. Доступен только при Region ≠ null. |
| `Back` | Закрыть оверлей, вернуть виджет в Default State **без сохранения**. |
| `Send` | Сохранить разметку, закрыть оверлей, вернуть в Default, показать уведомление. |

---

## Сценарии входа

### Вход через Annotate (cold start)

```
Состояние при открытии:
    Region = empty
    Tumor  = empty
    Send   = задизейблен
```

Врач рисует с нуля. Все его действия → action = 'created' в БД.

### Вход через Edit (после автодетекции)

```
Состояние при открытии зависит от результатов модели:

    Модель нашла Region + Tumor:
        Region = bbox (от модели)
        Tumor  = bbox (от модели)

    Модель нашла Region, но не Tumor:
        Region = bbox (от модели)
        Tumor  = null (модель сказала "опухоли нет")

    Модель не нашла Region:
        Region = null (модель сказала "областей нет")
        Tumor  = null (каскадно)
```

Врач видит текущее состояние, правит что считает неверным. Координаты модели визуально не помечаются — врач воспринимает как «текущее состояние которое можно поменять».

После Send бэкенд сравнивает финальное состояние с исходным от модели и определяет `action`:
- Если совпало (bbox с IoU ≥ 0.95 или оба null) → `action = 'confirmed'`
- Если изменено → `action = 'corrected'`

---

## Action маппинг при сохранении в БД

### Ключевое правило: bbox при confirmed = NULL

При `action = 'confirmed'` поле `bbox` в `localize_annotations` и `tumor_annotations` **остаётся NULL**, даже если у связанного detection есть bbox. Источник правды для координат — связанная запись через `detection_id`.

Причины:
- Нет рассинхрона данных при возможных обновлениях метаинформации в detection
- Чёткая семантика: `bbox` в annotations означает «то что человек сказал, отличное от модели». При confirmed человек ничего нового не сказал.
- Проще запросы при сборке датасета: для confirmed берём bbox из detection через JOIN, для corrected/created — из annotation.

Это согласуется с CHECK-ограничениями схемы БД (`confirmed` не требует bbox).

### Вход через Annotate (cold start)

```
Region.bbox  → localize_annotations.action = 'created', bbox = заданный
Region.null  → localize_annotations.action = 'created', bbox = NULL
Tumor.bbox   → tumor_annotations.action    = 'created', bbox = заданный
Tumor.null   → tumor_annotations.action    = 'created', bbox = NULL
```

### Вход через Detect → Approve

Врач не открывал оверлей, нажал Approve в Detect Actions. Создаются аннотации с `action='confirmed'` и `bbox=NULL` (источник координат — связанные detection).

**Подкейс A: модель нашла Region и Tumor**
```
localize_annotations:
    screen_id      = screenshot.id
    detection_id   = localize_detection.id
    bbox           = NULL          (источник — detection_id)
    action         = 'confirmed'
    monitor_index  = из detection
    annotator_id   = врач

tumor_annotations:
    localize_image_id = localize_image.id
    detection_id      = tumor_detection.id
    bbox              = NULL       (источник — detection_id)
    action            = 'confirmed'
    annotator_id      = врач
```

**Подкейс B: модель нашла Region, не нашла Tumor**
```
localize_annotations:  как в A
tumor_annotations:
    localize_image_id = localize_image.id
    detection_id      = tumor_detection.id   (с bbox=NULL у detection)
    bbox              = NULL
    action            = 'confirmed'          (подтверждаем «опухоли нет»)
```

**Подкейс C: модель не нашла Region**
```
localize_annotations:
    screen_id      = screenshot.id
    detection_id   = localize_detection.id   (с bbox=NULL у detection)
    bbox           = NULL
    action         = 'confirmed'             (подтверждаем «области нет»)

tumor_annotations:  записи НЕТ
    (нет localize_image, к которому привязывать)
```

### Вход через Detect → Edit (коррекция)

После Send бэкенд сравнивает финальное состояние с исходным от модели и определяет `action`:

```
Region совпадает с моделью   → action = 'confirmed', bbox = NULL
Region изменён                → action = 'corrected', bbox = новый
Region был bbox → стал null   → action = 'corrected', bbox = NULL
Region был null → стал bbox   → action = 'corrected', bbox = новый

Tumor совпадает с моделью    → action = 'confirmed', bbox = NULL
Tumor изменён                 → action = 'corrected', bbox = новый
Tumor был bbox → стал null    → action = 'corrected', bbox = NULL
Tumor был null → стал bbox    → action = 'corrected', bbox = новый
```

«Совпадает» для bbox: IoU с предсказанием модели ≥ 0.95 считается «не правил».
«Совпадает» для null: оба значения null.

### Сводная таблица действий и записей

| Действие врача | localize_annotations | tumor_annotations |
|---|---|---|
| Approve (модель: Region+Tumor) | confirmed, bbox=NULL | confirmed, bbox=NULL |
| Approve (модель: Region, Tumor=null) | confirmed, bbox=NULL | confirmed, bbox=NULL |
| Approve (модель: нет Region) | confirmed, bbox=NULL | нет записи |
| Edit → правка только Tumor | confirmed, bbox=NULL | corrected, bbox=новый |
| Edit → правка только Region | corrected, bbox=новый | corrected (если crop меняется) |
| Edit → «области нет» (через Mark Null Region) | corrected, bbox=NULL | corrected, bbox=NULL (если был detection) |
| Edit → «модель показала чушь» (Region=null) | corrected, bbox=NULL | corrected (если был) |
| Annotate с нуля (cold start) | created, bbox или NULL | created, bbox или NULL |

### Особый кейс: Edit когда модель показала ложную локализацию

Сценарий: модель обвела рамку вокруг не-снимка (например, окна терминала). Врач через Edit:
1. Видит предзаполненный Region и Tumor от модели
2. Нажимает `× Region` → Region=empty, Tumor=empty
3. Нажимает `Mark Null` для Region → Region=null, Tumor=null (каскадно)
4. Send

Запись: `localize_annotations.action='corrected', bbox=NULL`. Это **прямой false positive** в обучающих данных — ценнейший сигнал для дообучения локализатора.

---

## Поведение оверлея

### Покрытие экрана

- Оверлей покрывает **все мониторы** одновременно (прозрачное окно `screenSaver` уровня)
- Виджет с координатами появляется на том мониторе, где врач сделал последнее действие
- Под оверлеем экран **заморожен** на момент открытия — это снимок, не живая картинка
- Замороженный скриншот делается захватом всех мониторов через `mss`

### Независимость от хост-приложений

Оверлей рендерится в собственном слое поверх любых приложений (DICOM-вьюверы, браузеры, и т.д.). Все визуальные элементы (рамки bbox, подписи `REGION`/`TUMOR`, маркеры активного режима) — часть нашего оверлея.

**Ничто из UI хост-приложения не модифицируется.** Toolbar DICOM viewer'а, его меню и инструменты остаются нетронутыми. Это критично потому что:
- Разные больницы используют разные вьюверы (3D Slicer, OsiriX, RadiAnt, Bee DICOM Viewer и др.)
- Модификация чужого UI нарушает интеграционные обещания
- Любое обновление хост-приложения может сломать наш UI если мы в него встраиваемся

Если визуально кажется что наш маркер расположен в зоне toolbar вьювера — это потому что оверлей рендерится **поверх** этой зоны. На самом деле это два независимых слоя.

### Невозможность кликать вне оверлея

Оверлей перехватывает все клики. Пока он открыт, врач может:
- Рисовать bbox на оверлее
- Кликать кнопки виджета
- Нажать Esc или Back для отмены

Клик в любую другую часть экрана не уводит фокус. Это упрощает контроль состояния — нет необходимости в восстановлении черновика при потере фокуса.

### Промежуточная разметка не сохраняется

Если врач нажал Back или Esc — вся разметка теряется. Это намеренное решение для упрощения логики. При закрытии оверлея:
- Скриншот удаляется из памяти (не пишется в S3)
- Никакие записи в БД не создаются
- Виджет возвращается в Default State

---

## Координаты: системы и хранение

### Три системы координат

**Logical pixels** (то что видит врач на экране):
- Используются в UI виджета при отображении значений `x, y, w, h`
- Размерность экрана 1920×1080 на macOS Retina — это logical

**Physical pixels** (реальные пиксели скриншота):
- На Retina-дисплеях ×2 от logical (3840×2160 для 1920×1080 экрана)
- Скриншоты PNG в S3 хранятся в physical pixels
- Координаты bbox в БД хранятся в physical pixels

**Crop pixels** (координаты внутри crop'а):
- Используются для координат опухоли при сохранении в `tumor_annotations.bbox`
- Получаются вычитанием Region.x/y из глобальных координат Tumor

### Конвертация при отображении и сохранении

```python
# UI получает координаты в logical
ui_tumor = {"x": 1620, "y": 1080, "w": 50, "h": 50}

# При сохранении в БД:
dpi = monitor.dpi_scale_factor   # 2.0 для Retina

# Глобальные physical
physical_tumor_global = {
    "x": ui_tumor["x"] * dpi,
    "y": ui_tumor["y"] * dpi,
    "w": ui_tumor["w"] * dpi,
    "h": ui_tumor["h"] * dpi
}

# В пространство crop'а (для tumor_annotations.bbox)
physical_tumor_in_crop = {
    "x": physical_tumor_global["x"] - physical_region["x"],
    "y": physical_tumor_global["y"] - physical_region["y"],
    "w": physical_tumor_global["w"],
    "h": physical_tumor_global["h"]
}
```

Region хранится в координатах оригинала (`localize_annotations.bbox`), Tumor — в координатах crop'а (`tumor_annotations.bbox`). Это согласуется со схемой БД.

---

## Валидация при разметке

### Tumor внутри Region

Опухоль не может находиться вне области интереса. Реализация:

- При рисовании Tumor: если bbox выходит за границы Region — bbox подсвечивается **красной обводкой**
- Соответствующая группа координат в виджете тоже подсвечивается красным
- Маркер на bbox (цифра-индекс) становится красным
- **Send остаётся задизейбленным** пока есть невалидный bbox
- Врач исправляет bbox: либо двигает Tumor внутрь Region, либо расширяет Region чтобы включить Tumor, либо удаляет невалидный Tumor

**Никаких диалогов на Send.** Простая семантика: либо всё валидно и Send активен, либо нет.

### Минимальный размер bbox

```
if bbox.width < 10 or bbox.height < 10:
    bbox считается невалидным
    показать ошибку «bbox слишком маленький» на самом bbox
    Send задизейблен пока bbox не исправлен
```

Защита от случайных кликов. Применяется и к Region, и к Tumor.

### Пересечение Tumor bbox

Если две опухоли (в одном регионе) пересекаются — оба пересекающихся bbox подсвечиваются красным. Врач исправляет: разделяет на два невпересекающихся, объединяет в один, или удаляет один из них.

---

## Действия после Send

1. Скриншот сохраняется в S3 → `screenshots` запись
2. Если Region.bbox задан:
   - Делается crop по координатам Region
   - Crop сохраняется в S3 → `localize_images` запись
3. Создаётся `localize_annotations` с соответствующим action и bbox/null
4. Создаётся `tumor_annotations` с соответствующим action и bbox/null
5. Координаты Tumor конвертируются из глобальных в координаты crop'а перед записью
6. Если нет связи с сервером — все операции в локальном SQLite (sync_queue) до восстановления связи
7. Оверлей закрывается
8. Виджет возвращается в Default State
9. Показывается уведомление через `rumps.notification`: «Разметка сохранена»

---

## Прогон по 7 кейсам системы

Проверка покрытия всех сценариев системы (см. brainscan_schema.sql).

### Кейс 1: Авто, регион+опухоль найдены, подтверждено
Detect → Detect Actions → **Approve**. Не через оверлей.
Записи: `localize_annotations(confirmed, bbox=NULL)` + `tumor_annotations(confirmed, bbox=NULL)`.

### Кейс 2: Авто, регион+опухоль найдены, скорректировано
Detect → Detect Actions → **Edit** → оверлей с предзаполненными bbox от моделей. Врач правит. Send.
Записи: одна или обе аннотации с `action='corrected'` и новым bbox.

### Кейс 3: Авто, регион найден, нет опухоли, подтверждено
Detect → Detect Actions → **Approve**.
Записи: `localize_annotations(confirmed, bbox=NULL)` + `tumor_annotations(confirmed, bbox=NULL)`.

### Кейс 4: Авто, регион найден, нет опухоли, человек нашёл опухоль
Detect → Detect Actions → **Edit** → оверлей. Region предзаполнен bbox от модели, Tumor предзаполнен null. Врач делает `× Tumor` → `Add Tumor` → рисует. Send.
Записи: `localize_annotations(confirmed, bbox=NULL)` + `tumor_annotations(corrected, bbox=новый)`.

### Кейс 5: Авто, регион не найден, подтверждено
Detect → Detect Actions → **Approve**. Не через оверлей.
Запись: `localize_annotations(confirmed, bbox=NULL)`. Tumor аннотаций нет (нет crop'а).

### Кейс 6: Авто, регион не найден, человек нашёл
Detect → Detect Actions → **Edit** → оверлей. Region предзаполнен null, Tumor null (каскадно). Врач делает `× Region` → `Add Region` → рисует → `Add Tumor` / `Mark Null Tumor`. Send.
Записи: `localize_annotations(corrected, bbox=новый)` + `tumor_annotations(corrected или created)`.

### Кейс 7: Cold start, ручная с нуля
Default → **Annotate** → оверлей с пустого состояния. Add Region → Add Tumor (или Mark Null). Send.
Записи: `localize_annotations(created, bbox или NULL)` + `tumor_annotations(created, bbox или NULL)`.

### Особый кейс 8: Модель показала ложную локализацию (false positive)
Detect → Detect Actions → **Edit** → оверлей. Region предзаполнен bbox от модели (но там не снимок). Врач делает `× Region` → `Mark Null Region` → Tumor становится null каскадно. Send.
Запись: `localize_annotations(corrected, bbox=NULL)`. Если был tumor_detection — `tumor_annotations(corrected, bbox=NULL)`.
Это критически важный негативный пример для дообучения локализатора.

---

## Hotkeys (рекомендуемые)

```
R       — активировать Add Region
T       — активировать Add Tumor (если разрешён)
N       — Mark Null для последней активной сущности
Esc     — Back (закрыть без сохранения, с подтверждением)
Cmd+S   — Send (если активен)
Cmd+Z   — undo последнего bbox (опционально, для V2)
```

Hotkeys реализуются на уровне оверлея, активны пока он открыт.

---

## Edge cases

### Esc при заполненной разметке
- Диалог подтверждения «Отменить разметку? Все изменения будут потеряны»
- При подтверждении — полная очистка, возврат в Default State

### Multiple monitors
- Оверлей покрывает все мониторы
- Скриншот делается для всех мониторов сразу
- `monitor_index` в БД — определяется по местоположению Region.bbox
- Если Region.null или ручная разметка с нуля — берётся монитор где открыт виджет

### Retina + не-Retina одновременно
- Каждый монитор имеет свой `dpi_scale_factor`
- При сохранении в БД координаты приводятся к physical pixels этого конкретного монитора
- В `screenshots.screen_paths` JSONB хранится путь к скриншоту каждого монитора

### Send при отсутствии связи
- Все операции пишутся в локальный SQLite (`sync_queue`)
- Уведомление: «Разметка сохранена локально, будет отправлена при восстановлении связи»
- Виджет переходит в Default State, индикатор показывает offline + счётчик очереди
