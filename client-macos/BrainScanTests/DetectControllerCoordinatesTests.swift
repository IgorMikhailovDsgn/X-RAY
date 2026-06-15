import XCTest
@testable import BrainScan

/// Конверсия `BBoxResultDTO` (физические пиксели, top-left origin от API)
/// → `Bbox` (logical points, top-left origin — все рендер-канвасы
/// (DetectOverlayView, BboxCanvasView) — isFlipped=true; та же конвенция,
/// что у CoordinateConverter.physical в Annotate.
final class DetectControllerCoordinatesTests: XCTestCase {
    /// Retina 2880×1800 physical = 1440×900 logical, scaleFactor 2.
    private func retinaSnap(monitorIndex: Int = 0) -> PreparedSnapshot {
        // image не нужен для конверсии — используем заглушку через CGContext.
        let ctx = CGContext(
            data: nil, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )!
        let stub = ctx.makeImage()!
        return PreparedSnapshot(
            displayID: 1, monitorIndex: monitorIndex,
            frame: CGRect(x: 0, y: 0, width: 1440, height: 900),
            scaleFactor: 2.0,
            image: stub, png: Data()
        )
    }

    func test_top_left_pixel_maps_to_top_left_logical() {
        let snap = retinaSnap()
        // API bbox: top-left угол экрана, 200×100 в физических пикселях.
        let api = APIClient.BBoxResultDTO(x: 0, y: 0, w: 200, h: 100, confidence: 0.9)
        let bbox = DetectController.toBbox(api, snap: snap)
        // 200×100 px ÷ 2 = 100×50 pt; origin остаётся (0,0).
        XCTAssertEqual(bbox.rect.origin.x, 0)
        XCTAssertEqual(bbox.rect.origin.y, 0)
        XCTAssertEqual(bbox.rect.size.width, 100)
        XCTAssertEqual(bbox.rect.size.height, 50)
        XCTAssertEqual(bbox.monitorIndex, 0)
    }

    func test_bottom_right_pixel_maps_to_bottom_right_logical() {
        let snap = retinaSnap()
        // API bbox в physical: правый нижний угол, 400×200 px.
        let api = APIClient.BBoxResultDTO(x: 2480, y: 1600, w: 400, h: 200, confidence: 0.5)
        let bbox = DetectController.toBbox(api, snap: snap)
        // 400×200/2 = 200×100. x = 2480/2 = 1240, y = 1600/2 = 800.
        XCTAssertEqual(bbox.rect.origin.x, 1240)
        XCTAssertEqual(bbox.rect.origin.y, 800)
        XCTAssertEqual(bbox.rect.size.width, 200)
        XCTAssertEqual(bbox.rect.size.height, 100)
    }

    func test_non_retina_scale_1_passes_through() {
        // 1440×900 logical = 1440×900 physical (scaleFactor=1).
        let ctx = CGContext(
            data: nil, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )!
        let stub = ctx.makeImage()!
        let snap = PreparedSnapshot(
            displayID: 1, monitorIndex: 0,
            frame: CGRect(x: 0, y: 0, width: 1440, height: 900),
            scaleFactor: 1.0,
            image: stub, png: Data()
        )
        let api = APIClient.BBoxResultDTO(x: 100, y: 200, w: 50, h: 60, confidence: 0.7)
        let bbox = DetectController.toBbox(api, snap: snap)
        XCTAssertEqual(bbox.rect.origin.x, 100)
        XCTAssertEqual(bbox.rect.origin.y, 200)
        XCTAssertEqual(bbox.rect.size.width, 50)
        XCTAssertEqual(bbox.rect.size.height, 60)
    }

    func test_makeResult_no_regions_returns_empty_arrays() {
        let snap = retinaSnap()
        let resp = APIClient.DetectResponse(
            screenshotId: UUID(), monitorIndex: 0,
            localizeModelVersion: "v5", tumorModelVersion: "v6",
            regions: []
        )
        let result = DetectController.makeResult(from: resp, snap: snap)
        XCTAssertEqual(result.predictions.count, 1)
        XCTAssertTrue(result.predictions[0].regions.isEmpty)
        XCTAssertTrue(result.predictions[0].tumors.isEmpty)
        XCTAssertFalse(result.hasAnyRegion)
    }

    func test_makeResult_single_region_no_tumor() {
        let snap = retinaSnap()
        let resp = APIClient.DetectResponse(
            screenshotId: UUID(), monitorIndex: 0,
            localizeModelVersion: "v5", tumorModelVersion: nil,
            regions: [
                APIClient.RegionPredictionDTO(
                    region: APIClient.BBoxResultDTO(x: 100, y: 100, w: 400, h: 400, confidence: 0.99),
                    tumor: nil
                )
            ]
        )
        let result = DetectController.makeResult(from: resp, snap: snap)
        XCTAssertEqual(result.predictions[0].regions.count, 1)
        XCTAssertTrue(result.predictions[0].tumors.isEmpty)
        XCTAssertTrue(result.hasAnyRegion)
    }

    func test_makeResult_multiple_regions_partial_tumors() {
        let snap = retinaSnap()
        // 2 региона; tumor только у первого. Координаты tumor'а в physical px
        // уже сдвинуты сервером (мы здесь проверяем только клиент-конверсию).
        let resp = APIClient.DetectResponse(
            screenshotId: UUID(), monitorIndex: 0,
            localizeModelVersion: "v5", tumorModelVersion: "v6",
            regions: [
                APIClient.RegionPredictionDTO(
                    region: APIClient.BBoxResultDTO(x: 18, y: 346, w: 2894, h: 3534, confidence: 0.61),
                    tumor: APIClient.BBoxResultDTO(x: 218, y: 446, w: 160, h: 120, confidence: 0.85)
                ),
                APIClient.RegionPredictionDTO(
                    region: APIClient.BBoxResultDTO(x: 2896, y: 324, w: 2928, h: 3570, confidence: 0.60),
                    tumor: nil
                ),
            ]
        )
        let result = DetectController.makeResult(from: resp, snap: snap)
        let p = result.predictions[0]
        XCTAssertEqual(p.regions.count, 2)
        XCTAssertEqual(p.tumors.count, 1)
        // Первый регион — left half (физ. 18/2=9, 346/2=173).
        XCTAssertEqual(p.regions[0].rect.origin.x, 9)
        XCTAssertEqual(p.regions[0].rect.origin.y, 173)
        // Tumor конвертируется тем же делением на scaleFactor (без доп. сдвигов).
        XCTAssertEqual(p.tumors[0].rect.origin.x, 109)
        XCTAssertEqual(p.tumors[0].rect.origin.y, 223)
        XCTAssertTrue(result.hasAnyRegion)
    }
}
