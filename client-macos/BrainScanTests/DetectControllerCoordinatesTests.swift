import XCTest
@testable import BrainScan

/// Конверсия `BBoxResultDTO` (физические пиксели, top-left origin от API)
/// → `Bbox` (logical points, NSRect bottom-left origin монитора).
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

    func test_top_left_origin_maps_to_top_left_in_NSRect_with_yflip() {
        let snap = retinaSnap()
        // API bbox: top-left угол экрана, 200×100 в физических пикселях.
        let api = APIClient.BBoxResultDTO(x: 0, y: 0, w: 200, h: 100, confidence: 0.9)
        let bbox = DetectController.toBbox(api, snap: snap)
        // 200×100 px ÷ 2 = 100×50 pt. y = 900 - (0+100)/2 = 850.
        XCTAssertEqual(bbox.rect.origin.x, 0)
        XCTAssertEqual(bbox.rect.origin.y, 850)
        XCTAssertEqual(bbox.rect.size.width, 100)
        XCTAssertEqual(bbox.rect.size.height, 50)
        XCTAssertEqual(bbox.monitorIndex, 0)
    }

    func test_bottom_right_pixel_maps_to_bottom_right_in_logical() {
        let snap = retinaSnap()
        // API bbox в physical: правый нижний угол, 400×200 px.
        let api = APIClient.BBoxResultDTO(x: 2480, y: 1600, w: 400, h: 200, confidence: 0.5)
        let bbox = DetectController.toBbox(api, snap: snap)
        // 400×200/2 = 200×100. x = 2480/2 = 1240. y = 900 - (1600+200)/2 = 900 - 900 = 0.
        XCTAssertEqual(bbox.rect.origin.x, 1240)
        XCTAssertEqual(bbox.rect.origin.y, 0)
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
        XCTAssertEqual(bbox.rect.origin.y, 900 - (200 + 60))   // = 640
        XCTAssertEqual(bbox.rect.size.width, 50)
        XCTAssertEqual(bbox.rect.size.height, 60)
    }

    func test_makeResult_no_region_returns_empty_region_and_tumor() {
        let snap = retinaSnap()
        let resp = APIClient.DetectResponse(
            screenshotId: UUID(), monitorIndex: 0,
            localizeModelVersion: "v4", tumorModelVersion: "v5",
            region: nil, tumor: nil
        )
        let result = DetectController.makeResult(from: resp, snap: snap)
        XCTAssertEqual(result.predictions.count, 1)
        XCTAssertNil(result.predictions[0].region)
        XCTAssertNil(result.predictions[0].tumor)
        XCTAssertFalse(result.hasAnyRegion)
    }

    func test_makeResult_region_only_yields_tumor_nil() {
        let snap = retinaSnap()
        let resp = APIClient.DetectResponse(
            screenshotId: UUID(), monitorIndex: 0,
            localizeModelVersion: "v4", tumorModelVersion: nil,
            region: APIClient.BBoxResultDTO(x: 100, y: 100, w: 400, h: 400, confidence: 0.99),
            tumor: nil
        )
        let result = DetectController.makeResult(from: resp, snap: snap)
        XCTAssertNotNil(result.predictions[0].region)
        XCTAssertNil(result.predictions[0].tumor)
        XCTAssertTrue(result.hasAnyRegion)
    }
}
