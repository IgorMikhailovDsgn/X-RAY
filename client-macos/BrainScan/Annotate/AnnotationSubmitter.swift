import AppKit
import Foundation

/// Снимок монитора, подготовленный к загрузке: PNG (для multipart) и CGImage
/// (для генерации crop'а). Создаётся из свежего захвата (UI Send) или из PNG
/// на диске (replay из sync-очереди).
struct PreparedSnapshot {
    let displayID: CGDirectDisplayID
    let monitorIndex: Int
    let frame: CGRect
    let scaleFactor: CGFloat
    let image: CGImage
    let png: Data
}

typealias PreparedSnapshots = [Int: PreparedSnapshot]

/// Два потока отправки разметки:
///
/// 1. **Cold-start** (UploadPayload.existingScreenId == nil) — старый путь:
///    `prepare(geometry:)` свежий capture → POST /screenshots → per-item POST'ы
///    в `/localize-annotations`, `/localize-images`, `/tumor-annotations`.
/// 2. **Detect→Edit/Approve** (UploadPayload.existingScreenId != nil) —
///    Phase 10: один batch POST в `/api/v1/detect/annotations`. Без повторного
///    capture'а — скриншот уже на сервере. Crop'ы новых регионов сервер
///    создаёт сам. Сервер также подтягивает detection по `detection_id`,
///    считает correction_type/IoU/training_weight и нормализует action.
enum AnnotationSubmitter {
    static func prepare(geometry: [Int: DisplaySnapshot]) async throws -> PreparedSnapshots {
        let fresh = try await ScreenCapturer.captureForSubmit(geometry: geometry)
        var out: PreparedSnapshots = [:]
        for (index, snap) in fresh {
            guard let image = snap.image, let png = image.pngData() else { continue }
            out[index] = PreparedSnapshot(
                displayID: snap.displayID, monitorIndex: index,
                frame: snap.frame, scaleFactor: snap.scaleFactor,
                image: image, png: png
            )
        }
        guard !out.isEmpty else {
            throw NSError(domain: "BrainScan.Submit", code: -1, userInfo: [
                NSLocalizedDescriptionKey: "No screen images captured."
            ])
        }
        return out
    }

    /// Главная точка входа. Маршрутизация по `payload.existingScreenId`.
    static func upload(payload: UploadPayload, snapshots: PreparedSnapshots) async throws {
        if let screenId = payload.existingScreenId {
            try await uploadBatch(payload: payload, screenId: screenId)
        } else {
            try await uploadColdStart(payload: payload, snapshots: snapshots)
        }
    }

    // MARK: - Phase 10 batch path

    /// Один POST в `/api/v1/detect/annotations` со всем содержимым сессии.
    /// Сервер кропает новые регионы сам и считает correction_type.
    private static func uploadBatch(payload: UploadPayload, screenId: UUID) async throws {
        var localize: [APIClient.LocalizeBatchItem] = []
        var monitorIndexForRegion: [Int] = []
        var primaryMonitorIndex: Int? = payload.regions.first?.monitorIndex
            ?? payload.dismissedRegionDetections.first?.monitorIndex

        // 1. Текущие region-bbox'ы (positive: confirmed/corrected/created)
        //    Bbox с originalDetectionId → action='corrected' (сервер сам решит,
        //    что фактически совпадает с детектом → confirmed). Без detection_id →
        //    created.
        for box in payload.regions {
            let scale = backingScale(forMonitor: box.monitorIndex)
            let physical = CoordinateConverter.physical(box.rect.cgRect, dpi: scale)
            localize.append(
                APIClient.LocalizeBatchItem(
                    detectionId: box.originalDetectionId,
                    monitorIndex: box.monitorIndex,
                    bbox: BboxDTO(physical: physical),
                    action: box.originalDetectionId != nil ? "corrected" : "created"
                )
            )
            monitorIndexForRegion.append(box.monitorIndex)
        }

        // 2. Mark Null Region — собираем один или несколько items с bbox=NULL.
        //    Если в prefill были детекции → шлём по одному corrected+NULL на
        //    каждую (FP). Если детекций не было → created+NULL.
        if payload.regionNull {
            if !payload.dismissedRegionDetections.isEmpty {
                for dismissed in payload.dismissedRegionDetections {
                    localize.append(
                        APIClient.LocalizeBatchItem(
                            detectionId: dismissed.detectionId,
                            monitorIndex: dismissed.monitorIndex,
                            bbox: nil,
                            action: "corrected"
                        )
                    )
                    primaryMonitorIndex = primaryMonitorIndex ?? dismissed.monitorIndex
                }
            } else if let m = primaryMonitorIndex {
                localize.append(
                    APIClient.LocalizeBatchItem(
                        detectionId: nil,
                        monitorIndex: m,
                        bbox: nil,
                        action: "created"
                    )
                )
            }
        }

        // 3. Опционально: dismissed-детекции при НЕ-mark-null Region (юзер
        //    удалил конкретный prefill-bbox, а остальные оставил). FP-сигнал
        //    для именно той детекции.
        if !payload.regionNull {
            for dismissed in payload.dismissedRegionDetections {
                localize.append(
                    APIClient.LocalizeBatchItem(
                        detectionId: dismissed.detectionId,
                        monitorIndex: dismissed.monitorIndex,
                        bbox: nil,
                        action: "corrected"
                    )
                )
            }
        }

        // 4. Tumor-items. region_index = индекс первого ненулевого региона в
        //    localize-массиве (для текущего этапа: tumors прикрепляются к первому
        //    region'у, так же как делает легаси-путь).
        var tumors: [APIClient.TumorBatchItem] = []
        let firstRegionIndex = indexOfFirstPositiveRegion(items: localize)
        if let firstRegionIndex {
            // 4a. Текущие tumor-bbox'ы (positive).
            for box in payload.tumors {
                guard let regionBox = payload.regions.first else { continue }
                let scale = backingScale(forMonitor: box.monitorIndex)
                let physTumor = CoordinateConverter.physical(box.rect.cgRect, dpi: scale)
                let physRegion = CoordinateConverter.physical(regionBox.rect.cgRect, dpi: scale)
                let inCrop = CGRect(
                    x: physTumor.origin.x - physRegion.origin.x,
                    y: physTumor.origin.y - physRegion.origin.y,
                    width: physTumor.width, height: physTumor.height
                )
                tumors.append(
                    APIClient.TumorBatchItem(
                        regionIndex: firstRegionIndex,
                        detectionId: box.originalDetectionId,
                        bbox: BboxDTO(physical: inCrop),
                        action: box.originalDetectionId != nil ? "corrected" : "created"
                    )
                )
            }

            // 4b. Mark Null Tumor / dismissed-tumor-детекции.
            if payload.tumorNull, !payload.dismissedTumorDetections.isEmpty {
                for dismissed in payload.dismissedTumorDetections {
                    tumors.append(
                        APIClient.TumorBatchItem(
                            regionIndex: firstRegionIndex,
                            detectionId: dismissed.detectionId,
                            bbox: nil,
                            action: "corrected"
                        )
                    )
                }
            } else if payload.tumorNull {
                tumors.append(
                    APIClient.TumorBatchItem(
                        regionIndex: firstRegionIndex,
                        detectionId: nil,
                        bbox: nil,
                        action: "created"
                    )
                )
            } else {
                // Юзер удалил отдельные prefill-tumors, остальные оставил.
                for dismissed in payload.dismissedTumorDetections {
                    tumors.append(
                        APIClient.TumorBatchItem(
                            regionIndex: firstRegionIndex,
                            detectionId: dismissed.detectionId,
                            bbox: nil,
                            action: "corrected"
                        )
                    )
                }
            }
        }

        let req = APIClient.BatchAnnotationsRequest(
            screenId: screenId, localize: localize, tumors: tumors
        )
        _ = try await APIClient.shared.batchAnnotations(req)
    }

    // Возвращает индекс первого region-item'а с bbox≠nil. Tumors привязываются
    // к нему через region_index (cascade-валидация сервера это требует).
    private static func indexOfFirstPositiveRegion(
        items: [APIClient.LocalizeBatchItem]
    ) -> Int? {
        items.firstIndex { $0.bbox != nil }
    }

    private static func backingScale(forMonitor monitorIndex: Int) -> CGFloat {
        let screens = NSScreen.screens
        if monitorIndex < screens.count {
            return screens[monitorIndex].backingScaleFactor
        }
        return NSScreen.main?.backingScaleFactor ?? 2.0
    }

    // MARK: - Cold-start legacy path

    private static func uploadColdStart(
        payload: UploadPayload, snapshots: PreparedSnapshots
    ) async throws {
        let api = APIClient.shared

        // 1. Скриншоты всех мониторов одной сессией.
        let pngs = snapshots.mapValues(\.png)
        let screen = try await api.uploadScreenshots(images: pngs)

        // 2a. Region=null («области нет нигде») → negative localize-аннотация на
        // КАЖДЫЙ захваченный монитор (каждый full-screenshot — валидный negative).
        // Crop/localize-image и tumor не создаём (нет области → нет crop'а).
        if payload.regionNull {
            for monitorIndex in snapshots.keys.sorted() {
                _ = try await api.createLocalizeAnnotation(
                    .init(screenId: screen.id, detectionId: nil,
                          monitorIndex: monitorIndex, bbox: nil, action: "created")
                )
            }
            return
        }

        // 2b. Region: annotation → crop → localize-image.
        var firstLocalizeImageId: UUID?
        for region in payload.regions {
            guard let snap = snapshots[region.monitorIndex] else { continue }
            let physical = CoordinateConverter.physical(region.rect.cgRect, dpi: snap.scaleFactor)
            let bboxDTO = BboxDTO(physical: physical)
            let annotation = try await api.createLocalizeAnnotation(
                .init(screenId: screen.id, detectionId: nil,
                      monitorIndex: region.monitorIndex, bbox: bboxDTO, action: "created")
            )
            guard let cropPNG = makeCropPNG(image: snap.image, frame: snap.frame,
                                            regionLogical: region.rect.cgRect)
            else { continue }
            let img = try await api.uploadLocalizeImage(
                screenId: screen.id, monitorIndex: region.monitorIndex, bbox: bboxDTO,
                detectionId: nil, annotationId: annotation.id, crop: cropPNG
            )
            if firstLocalizeImageId == nil { firstLocalizeImageId = img.id }
        }

        // 3. Tumor → tumor-annotations (привязка к localize-image первого региона).
        if let lid = firstLocalizeImageId {
            if payload.tumorNull {
                // Опухоли нет на crop'е → negative tumor-аннотация (bbox=null).
                _ = try await api.createTumorAnnotation(
                    .init(localizeImageId: lid, detectionId: nil,
                          bbox: nil, action: "created")
                )
            } else if let firstRegion = payload.regions.first,
                      let snap = snapshots[firstRegion.monitorIndex] {
                for tumor in payload.tumors {
                    let inCrop = CoordinateConverter.tumorInCrop(
                        tumorLogical: tumor.rect.cgRect,
                        regionLogical: firstRegion.rect.cgRect,
                        dpi: snap.scaleFactor
                    )
                    _ = try await api.createTumorAnnotation(
                        .init(localizeImageId: lid, detectionId: nil,
                              bbox: BboxDTO(physical: inCrop), action: "created")
                    )
                }
            }
        }
    }

    // MARK: - Helpers

    /// Crop из CGImage по region.rect (logical). Используются фактические размеры
    /// захваченного изображения — не зависим от `SCStreamConfiguration` параметров.
    private static func makeCropPNG(image: CGImage, frame: CGRect,
                                    regionLogical: CGRect) -> Data? {
        let scaleX = CGFloat(image.width) / frame.size.width
        let scaleY = CGFloat(image.height) / frame.size.height
        let cropRect = CGRect(
            x: (regionLogical.origin.x * scaleX).rounded(),
            y: (regionLogical.origin.y * scaleY).rounded(),
            width: (regionLogical.size.width * scaleX).rounded(),
            height: (regionLogical.size.height * scaleY).rounded()
        ).integral
        guard let cropped = image.cropping(to: cropRect) else { return nil }
        return cropped.pngData()
    }
}

extension CGImage {
    /// PNG-байты CGImage через `NSBitmapImageRep`. Возвращает nil если не удалось
    /// закодировать (редко на корректных RGBA-изображениях).
    func pngData() -> Data? {
        let rep = NSBitmapImageRep(cgImage: self)
        return rep.representation(using: .png, properties: [:])
    }
}
