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

/// Два независимых шага отправки разметки:
/// - `prepare(geometry:)` — захват свежих скриншотов всех мониторов (на UI Send).
/// - `upload(payload:snapshots:)` — отправка screenshots → annotations → localize-images
///   → tumor-annotations. Используется и UI Send, и replay из sync-очереди.
///
/// Null-сущности при cold-start (action='created' + bbox=NULL) пока пропускаются —
/// DB CHECK не пускает, см. комментарии в коде. Уточним отдельным экшеном позже.
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

    static func upload(payload: UploadPayload, snapshots: PreparedSnapshots) async throws {
        let api = APIClient.shared

        // 1. Скриншоты всех мониторов одной сессией.
        let pngs = snapshots.mapValues(\.png)
        let screen = try await api.uploadScreenshots(images: pngs)

        // 2. Region: annotation → crop → localize-image.
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
        if let lid = firstLocalizeImageId, let firstRegion = payload.regions.first,
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
