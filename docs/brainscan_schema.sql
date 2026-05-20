-- =============================================================================
-- BrainScan Database Schema
-- =============================================================================
-- Система детекции опухолей мозга по КТ/МРТ снимкам
-- PostgreSQL 16+
--
-- Архитектурные принципы:
-- 1. Хранилище и предсказания моделей — отдельные сущности
-- 2. Детекции моделей и аннотации людей не смешиваются (никаких UPDATE)
-- 3. localize_images — связующее звено между локализатором и детектором
-- 4. NULL-семантика однозначна:
--    - в *_detections.bbox: NULL = модель отработала, ничего не нашла
--    - в *_annotations.bbox: NULL = человек подтвердил отсутствие (с action)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- для gen_random_uuid()


-- =============================================================================
-- MLOPS: Datasets, Models, Deployments
-- =============================================================================

-- Версии датасетов для обучения
CREATE TABLE datasets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type      TEXT NOT NULL,
    version         TEXT NOT NULL,
    size_total      INT NOT NULL,
    size_train      INT NOT NULL,
    size_val        INT NOT NULL,
    manifest_path   TEXT NOT NULL,           -- s3://.../datasets/{type}/v{N}/manifest.json
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_datasets_model_type
        CHECK (model_type IN ('localize', 'tumor')),
    CONSTRAINT chk_datasets_sizes
        CHECK (size_total = size_train + size_val),
    CONSTRAINT uq_datasets_type_version
        UNIQUE (model_type, version)
);


-- Версии моделей
CREATE TABLE models (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type      TEXT NOT NULL,
    version         TEXT NOT NULL,
    trained_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    dataset_id      UUID REFERENCES datasets(id),
    -- nullable: первая seed-модель может быть обучена вне системы
    artifact_path   TEXT NOT NULL,           -- s3://.../models/{type}/v{N}/weights.pt
    metrics         JSONB NOT NULL,
    -- localize: {"iou":0.87, "precision":0.91, "recall":0.89, "f1":0.90}
    -- tumor:    {"accuracy":0.94, "precision":0.93, "recall":0.95,
    --            "f1":0.94, "auc_roc":0.97, "specificity":0.92}
    status          TEXT NOT NULL DEFAULT 'candidate',

    CONSTRAINT chk_models_model_type
        CHECK (model_type IN ('localize', 'tumor')),
    CONSTRAINT chk_models_status
        CHECK (status IN ('candidate', 'prod', 'archived', 'failed')),
    CONSTRAINT uq_models_type_version
        UNIQUE (model_type, version)
);

CREATE INDEX idx_models_type_status
    ON models(model_type, status);


-- История деплоев моделей в production
CREATE TABLE deployments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id        UUID NOT NULL REFERENCES models(id),
    deployed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    deployed_by     TEXT NOT NULL,           -- 'auto' | 'manual:{user_id}'
    rollback_of     UUID REFERENCES deployments(id),
    -- заполнено если этот деплой — откат предыдущего
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    notes           TEXT
);

CREATE INDEX idx_deployments_active
    ON deployments(model_id, is_active)
    WHERE is_active = TRUE;


-- =============================================================================
-- ОПЕРАЦИОННЫЕ: Screenshots
-- =============================================================================

-- Сессии захвата экрана
CREATE TABLE screenshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    device_id       TEXT NOT NULL,           -- идентификатор рабочей станции
    monitor_count   INT NOT NULL,
    screen_paths    JSONB NOT NULL
    -- {"0": "s3://.../screen_m0.png",
    --  "1": "s3://.../screen_m1.png"}
    -- ключ = monitor_index как строка, значение = URL файла
);

CREATE INDEX idx_screenshots_device_date
    ON screenshots(device_id, captured_at DESC);


-- =============================================================================
-- МОДЕЛЬ 1: Локализатор — детекции и аннотации
-- =============================================================================

-- Результаты работы модели локализации области снимка
CREATE TABLE localize_detections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    screen_id       UUID NOT NULL REFERENCES screenshots(id),
    model_id        UUID NOT NULL REFERENCES models(id),
    monitor_index   INT NOT NULL,
    bbox            JSONB,
    -- {"x":13, "y":4, "w":490, "h":341} в координатах оригинала
    -- NULL = модель отработала, областей на этом мониторе не нашла
    meta_json_path  TEXT,
    -- s3://.../meta.json: scale_factor, pad_x, pad_y, class_scores
    inferred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_localize_detections_screen
    ON localize_detections(screen_id);


-- Аннотации специалиста по локализации
CREATE TABLE localize_annotations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    screen_id       UUID NOT NULL REFERENCES screenshots(id),
    detection_id    UUID REFERENCES localize_detections(id),
    -- NULL = ручная разметка с нуля (cold start или модель не запускалась)
    monitor_index   INT NOT NULL,
    bbox            JSONB,
    -- координаты в оригинале
    -- NULL = человек подтвердил отсутствие области (action='confirmed')
    action          TEXT NOT NULL,
    -- 'confirmed' — соглашаемся с моделью (bbox может быть NULL)
    -- 'corrected' — модель сказала одно, человек дал другое (bbox обязателен)
    -- 'created'   — ручная разметка с нуля (detection_id NULL, bbox обязателен)
    annotator_id    TEXT NOT NULL,
    annotated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    meta_json_path  TEXT,

    CONSTRAINT chk_loc_ann_action
        CHECK (action IN ('confirmed', 'corrected', 'created')),
    CONSTRAINT chk_loc_ann_action_combinations
        CHECK (
            (action = 'confirmed' AND detection_id IS NOT NULL)
            OR
            (action = 'corrected' AND detection_id IS NOT NULL
                                  AND bbox IS NOT NULL)
            OR
            (action = 'created'   AND detection_id IS NULL
                                  AND bbox IS NOT NULL)
        )
);

CREATE INDEX idx_localize_annotations_screen
    ON localize_annotations(screen_id);
CREATE INDEX idx_localize_annotations_detection
    ON localize_annotations(detection_id);
CREATE INDEX idx_localize_annotations_annotated_at
    ON localize_annotations(annotated_at);
-- индекс по annotated_at нужен для триггера дообучения


-- =============================================================================
-- ПРОМЕЖУТОЧНАЯ СУЩНОСТЬ: Crop'ы области интереса
-- =============================================================================

-- Обрезки области интереса — вход для детектора опухолей
-- Связующее звено между моделями локализации и детекции
CREATE TABLE localize_images (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    screen_id       UUID NOT NULL REFERENCES screenshots(id),
    detection_id    UUID REFERENCES localize_detections(id),
    annotation_id   UUID REFERENCES localize_annotations(id),
    -- хотя бы одна из ссылок (detection_id или annotation_id) обязательна
    monitor_index   INT NOT NULL,
    bbox            JSONB NOT NULL,
    -- координаты crop'а в оригинале (для воспроизводимости)
    localize_path   TEXT NOT NULL,           -- s3://.../localize/{id}.png
    meta_json_path  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_loc_img_source
        CHECK (detection_id IS NOT NULL OR annotation_id IS NOT NULL)
);

CREATE INDEX idx_localize_images_screen
    ON localize_images(screen_id);
CREATE INDEX idx_localize_images_detection
    ON localize_images(detection_id);
CREATE INDEX idx_localize_images_annotation
    ON localize_images(annotation_id);


-- =============================================================================
-- МОДЕЛЬ 2: Детектор опухоли — детекции и аннотации
-- =============================================================================

-- Результаты работы модели детекции опухоли
CREATE TABLE tumor_detections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    localize_image_id   UUID NOT NULL REFERENCES localize_images(id),
    model_id            UUID NOT NULL REFERENCES models(id),
    bbox                JSONB,
    -- координаты опухоли в пространстве crop'а (не оригинала)
    -- NULL = модель отработала, опухоли не нашла
    meta_json_path      TEXT,
    inferred_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tumor_detections_image
    ON tumor_detections(localize_image_id);


-- Аннотации специалиста по опухоли
CREATE TABLE tumor_annotations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    localize_image_id   UUID NOT NULL REFERENCES localize_images(id),
    detection_id        UUID REFERENCES tumor_detections(id),
    -- NULL = ручная разметка, детектор не запускался
    bbox                JSONB,
    -- координаты опухоли в пространстве crop'а
    -- NULL = человек подтвердил отсутствие опухоли (action='confirmed')
    --        или скорректировал «модель ошиблась, опухоли нет» (action='corrected')
    action              TEXT NOT NULL,
    annotator_id        TEXT NOT NULL,
    annotated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    meta_json_path      TEXT,

    CONSTRAINT chk_tum_ann_action
        CHECK (action IN ('confirmed', 'corrected', 'created')),
    CONSTRAINT chk_tum_ann_action_combinations
        CHECK (
            (action = 'confirmed' AND detection_id IS NOT NULL)
            OR
            (action = 'corrected' AND detection_id IS NOT NULL)
            OR
            (action = 'created'   AND detection_id IS NULL
                                  AND bbox IS NOT NULL)
        )
    -- 'confirmed': подтверждаем результат модели как есть
    --              (bbox=null если модель сказала "нет опухоли")
    -- 'corrected': исправляем результат модели
    --              (bbox может быть NULL если человек сказал
    --               "модель нашла опухоль, но её нет")
    -- 'created':   ручная разметка без работы модели
);

CREATE INDEX idx_tumor_annotations_image
    ON tumor_annotations(localize_image_id);
CREATE INDEX idx_tumor_annotations_detection
    ON tumor_annotations(detection_id);
CREATE INDEX idx_tumor_annotations_annotated_at
    ON tumor_annotations(annotated_at);
-- индекс по annotated_at нужен для триггера дообучения


-- =============================================================================
-- ПРИМЕРЫ ЗАПРОСОВ
-- =============================================================================

-- Сборка датасета для дообучения детектора опухоли
-- ----------------------------------------------------
-- SELECT
--     li.id AS crop_id,
--     li.localize_path,
--     ta.bbox AS tumor_bbox,
--     CASE WHEN ta.bbox IS NULL THEN 'no_tumor' ELSE 'tumor' END AS label,
--     ta.action,
--     ta.annotator_id
-- FROM localize_images li
-- JOIN tumor_annotations ta ON ta.localize_image_id = li.id
-- WHERE ta.action IN ('confirmed', 'corrected', 'created')
--   AND ta.annotated_at > (
--       SELECT COALESCE(MAX(created_at), '1970-01-01')
--       FROM datasets WHERE model_type = 'tumor'
--   )
-- ORDER BY ta.annotated_at;


-- Сборка датасета для дообучения локализатора
-- ----------------------------------------------------
-- SELECT
--     s.id AS screen_id,
--     s.screen_paths,
--     la.monitor_index,
--     la.bbox AS region_bbox,
--     CASE WHEN la.bbox IS NULL THEN 'no_region' ELSE 'region' END AS label,
--     la.action,
--     la.annotator_id
-- FROM screenshots s
-- JOIN localize_annotations la ON la.screen_id = s.id
-- WHERE la.action IN ('confirmed', 'corrected', 'created')
--   AND la.annotated_at > (
--       SELECT COALESCE(MAX(created_at), '1970-01-01')
--       FROM datasets WHERE model_type = 'localize'
--   )
-- ORDER BY la.annotated_at;


-- Триггер дообучения детектора (счётчик новых аннотаций)
-- ----------------------------------------------------
-- SELECT COUNT(*)
-- FROM tumor_annotations
-- WHERE annotated_at > (
--     SELECT COALESCE(MAX(created_at), '1970-01-01')
--     FROM datasets WHERE model_type = 'tumor'
-- );
-- если >= 1000 → запуск Celery-задачи build_dataset_and_train('tumor')


-- Откат модели в production
-- ----------------------------------------------------
-- BEGIN;
--   UPDATE deployments
--   SET is_active = FALSE
--   WHERE model_id IN (
--       SELECT id FROM models WHERE model_type = 'tumor' AND status = 'prod'
--   );
--
--   UPDATE models SET status = 'archived'
--   WHERE model_type = 'tumor' AND status = 'prod';
--
--   UPDATE models SET status = 'prod'
--   WHERE id = :target_model_id;
--
--   INSERT INTO deployments (model_id, deployed_by, rollback_of, is_active)
--   VALUES (:target_model_id, 'manual:user_42', :previous_deployment_id, TRUE);
-- COMMIT;
