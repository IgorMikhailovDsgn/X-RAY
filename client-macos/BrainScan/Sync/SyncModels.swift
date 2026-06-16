import CoreGraphics
import Foundation

/// JSON-сериализуемый прямоугольник (CGRect не Codable из коробки).
struct CodableRect: Codable, Equatable {
    let x: Double
    let y: Double
    let w: Double
    let h: Double

    init(_ rect: CGRect) {
        x = Double(rect.origin.x); y = Double(rect.origin.y)
        w = Double(rect.size.width); h = Double(rect.size.height)
    }

    var cgRect: CGRect { CGRect(x: x, y: y, width: w, height: h) }
}

/// Сериализованный bbox для отправки/очереди.
struct BboxPayload: Codable, Equatable {
    let id: UUID
    let monitorIndex: Int
    let rect: CodableRect
    /// Phase 10: detection_id, на основе которой bbox попал в модель через
    /// Detect→Edit prefill. nil для cold-start / новых bbox.
    let originalDetectionId: UUID?

    init(from bbox: Bbox) {
        id = bbox.id
        monitorIndex = bbox.monitorIndex
        rect = CodableRect(bbox.rect)
        originalDetectionId = bbox.originalDetectionId
    }
}

extension BboxPayload {
    /// Backward-compat: декодит старые записи sync-очереди без originalDetectionId.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        monitorIndex = try c.decode(Int.self, forKey: .monitorIndex)
        rect = try c.decode(CodableRect.self, forKey: .rect)
        originalDetectionId = try c.decodeIfPresent(UUID.self, forKey: .originalDetectionId)
    }
}

/// Phase 10: prefill-детекция, чьи bbox были удалены пользователем в Edit-флоу.
/// Сервер получает её как `action='corrected' + bbox=NULL + detection_id` —
/// FP-сигнал для модели.
struct DismissedDetection: Codable, Equatable {
    let detectionId: UUID
    let monitorIndex: Int
}

/// Полезная нагрузка одной отправки разметки. `regions`/`tumors` — нарисованные
/// bbox (positive); `regionNull`/`tumorNull` — флаги «Mark Null» (negative:
/// области/опухоли нет).
///
/// Phase 10 расширения:
/// - `existingScreenId` — если задан, AnnotationSubmitter не делает повторный
///   capture (сценарий Detect→Edit/Approve: скриншот уже у сервера).
/// - `dismissedRegionDetections`/`dismissedTumorDetections` — `originalDetectionId`
///   тех bbox, которые были в prefill, но были удалены пользователем (Mark Null
///   region/tumor или ручное удаление). Сервер получает их как
///   `corrected + bbox=NULL`, чтобы FP-сигнал не потерялся.
struct UploadPayload: Codable, Equatable {
    let regions: [BboxPayload]
    let tumors: [BboxPayload]
    let regionNull: Bool
    let tumorNull: Bool
    let existingScreenId: UUID?
    let dismissedRegionDetections: [DismissedDetection]
    let dismissedTumorDetections: [DismissedDetection]

    static func from(model: AnnotationModel, existingScreenId: UUID? = nil) -> UploadPayload {
        UploadPayload(
            regions: model.regionState.bboxes.map(BboxPayload.init(from:)),
            tumors: model.tumorState.bboxes.map(BboxPayload.init(from:)),
            regionNull: model.regionState.isNull,
            tumorNull: model.tumorState.isNull,
            existingScreenId: existingScreenId,
            dismissedRegionDetections: model.dismissedRegionDetections,
            dismissedTumorDetections: model.dismissedTumorDetections
        )
    }
}

extension UploadPayload {
    /// Backward-compat: старые манифесты в sync-очереди без regionNull/tumorNull/Phase 10-полей
    /// декодятся с дефолтами (поведение как раньше — нули и dismissed не слались).
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        regions = try c.decode([BboxPayload].self, forKey: .regions)
        tumors = try c.decode([BboxPayload].self, forKey: .tumors)
        regionNull = try c.decodeIfPresent(Bool.self, forKey: .regionNull) ?? false
        tumorNull = try c.decodeIfPresent(Bool.self, forKey: .tumorNull) ?? false
        existingScreenId = try c.decodeIfPresent(UUID.self, forKey: .existingScreenId)
        dismissedRegionDetections = (try c.decodeIfPresent(
            [DismissedDetection].self, forKey: .dismissedRegionDetections
        )) ?? []
        dismissedTumorDetections = (try c.decodeIfPresent(
            [DismissedDetection].self, forKey: .dismissedTumorDetections
        )) ?? []
    }
}

/// Метаданные одного монитора, сохранённые рядом со скриншотами.
struct MonitorMeta: Codable, Equatable {
    let monitorIndex: Int
    let displayID: UInt32
    let frame: CodableRect
    let scaleFactor: Double
}

/// Манифест одного элемента очереди: payload + геометрия мониторов + дата.
/// PNG-снимки лежат рядом в `<id>/screen_<index>.png`.
struct SyncManifest: Codable, Equatable {
    let id: UUID            // id элемента очереди (не путать с screen_id бэкенда)
    let createdAt: Date
    let payload: UploadPayload
    let monitors: [MonitorMeta]
}
