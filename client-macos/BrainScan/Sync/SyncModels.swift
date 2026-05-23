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

    init(from bbox: Bbox) {
        id = bbox.id
        monitorIndex = bbox.monitorIndex
        rect = CodableRect(bbox.rect)
    }
}

/// Полезная нагрузка одной отправки разметки. Сейчас хранятся только
/// конкретные bbox (null-сущности пропускаются на бэке — см. submitter).
struct UploadPayload: Codable, Equatable {
    let regions: [BboxPayload]
    let tumors: [BboxPayload]

    static func from(model: AnnotationModel) -> UploadPayload {
        UploadPayload(
            regions: model.regionState.bboxes.map(BboxPayload.init(from:)),
            tumors: model.tumorState.bboxes.map(BboxPayload.init(from:))
        )
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
