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

    private let screenId = UUID()

    func test_top_left_pixel_maps_to_top_left_logical() {
        let snap = retinaSnap()
        let api = APIClient.BBoxResultDTO(
            x: 0, y: 0, w: 200, h: 100, confidence: 0.9, detectionId: nil
        )
        let bbox = DetectController.toBbox(api, snap: snap)
        XCTAssertEqual(bbox.rect.origin.x, 0)
        XCTAssertEqual(bbox.rect.origin.y, 0)
        XCTAssertEqual(bbox.rect.size.width, 100)
        XCTAssertEqual(bbox.rect.size.height, 50)
        XCTAssertEqual(bbox.monitorIndex, 0)
    }

    func test_bottom_right_pixel_maps_to_bottom_right_logical() {
        let snap = retinaSnap()
        let api = APIClient.BBoxResultDTO(
            x: 2480, y: 1600, w: 400, h: 200, confidence: 0.5, detectionId: nil
        )
        let bbox = DetectController.toBbox(api, snap: snap)
        XCTAssertEqual(bbox.rect.origin.x, 1240)
        XCTAssertEqual(bbox.rect.origin.y, 800)
        XCTAssertEqual(bbox.rect.size.width, 200)
        XCTAssertEqual(bbox.rect.size.height, 100)
    }

    func test_non_retina_scale_1_passes_through() {
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
        let api = APIClient.BBoxResultDTO(
            x: 100, y: 200, w: 50, h: 60, confidence: 0.7, detectionId: nil
        )
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
        let result = DetectController.makeResult(from: resp, screen: screenId, snap: snap)
        XCTAssertEqual(result.predictions.count, 1)
        XCTAssertTrue(result.predictions[0].regions.isEmpty)
        XCTAssertFalse(result.hasAnyRegion)
        XCTAssertEqual(result.screenId, screenId)
    }

    func test_makeResult_single_region_no_tumor_preserves_detection_id() {
        let snap = retinaSnap()
        let regionDetectionId = UUID()
        let resp = APIClient.DetectResponse(
            screenshotId: UUID(), monitorIndex: 0,
            localizeModelVersion: "v5", tumorModelVersion: nil,
            regions: [
                APIClient.RegionPredictionDTO(
                    region: APIClient.BBoxResultDTO(
                        x: 100, y: 100, w: 400, h: 400, confidence: 0.99,
                        detectionId: regionDetectionId
                    ),
                    tumor: nil
                )
            ]
        )
        let result = DetectController.makeResult(from: resp, screen: screenId, snap: snap)
        let detected = result.predictions[0].regions
        XCTAssertEqual(detected.count, 1)
        XCTAssertEqual(detected[0].regionDetectionId, regionDetectionId)
        XCTAssertNil(detected[0].tumor)
        XCTAssertNil(detected[0].tumorDetectionId)
        XCTAssertTrue(result.hasAnyRegion)
    }

    func test_makeResult_multiple_regions_with_per_region_tumor_detection_ids() {
        let snap = retinaSnap()
        let regionDetectionId1 = UUID()
        let regionDetectionId2 = UUID()
        let tumorDetectionId1 = UUID()
        let resp = APIClient.DetectResponse(
            screenshotId: UUID(), monitorIndex: 0,
            localizeModelVersion: "v5", tumorModelVersion: "v6",
            regions: [
                APIClient.RegionPredictionDTO(
                    region: APIClient.BBoxResultDTO(
                        x: 18, y: 346, w: 2894, h: 3534, confidence: 0.61,
                        detectionId: regionDetectionId1
                    ),
                    tumor: APIClient.BBoxResultDTO(
                        x: 218, y: 446, w: 160, h: 120, confidence: 0.85,
                        detectionId: tumorDetectionId1
                    )
                ),
                APIClient.RegionPredictionDTO(
                    region: APIClient.BBoxResultDTO(
                        x: 2896, y: 324, w: 2928, h: 3570, confidence: 0.60,
                        detectionId: regionDetectionId2
                    ),
                    tumor: nil
                ),
            ]
        )
        let result = DetectController.makeResult(from: resp, screen: screenId, snap: snap)
        let detected = result.predictions[0].regions
        XCTAssertEqual(detected.count, 2)

        // Первый регион — left half (физ. 18/2=9, 346/2=173) с tumor.
        XCTAssertEqual(detected[0].region.rect.origin.x, 9)
        XCTAssertEqual(detected[0].region.rect.origin.y, 173)
        XCTAssertEqual(detected[0].regionDetectionId, regionDetectionId1)
        XCTAssertNotNil(detected[0].tumor)
        XCTAssertEqual(detected[0].tumorDetectionId, tumorDetectionId1)

        // Второй регион — без tumor.
        XCTAssertEqual(detected[1].regionDetectionId, regionDetectionId2)
        XCTAssertNil(detected[1].tumor)
        XCTAssertNil(detected[1].tumorDetectionId)
    }

    func test_prefillStates_propagates_original_detection_ids_to_bboxes() {
        let snap = retinaSnap()
        let regionDetectionId = UUID()
        let tumorDetectionId = UUID()
        let resp = APIClient.DetectResponse(
            screenshotId: UUID(), monitorIndex: 0,
            localizeModelVersion: "v5", tumorModelVersion: "v6",
            regions: [
                APIClient.RegionPredictionDTO(
                    region: APIClient.BBoxResultDTO(
                        x: 100, y: 100, w: 200, h: 200, confidence: 0.95,
                        detectionId: regionDetectionId
                    ),
                    tumor: APIClient.BBoxResultDTO(
                        x: 150, y: 150, w: 50, h: 50, confidence: 0.8,
                        detectionId: tumorDetectionId
                    )
                )
            ]
        )
        let result = DetectController.makeResult(from: resp, screen: screenId, snap: snap)
        let (region, tumor) = result.prefillStates()

        XCTAssertEqual(region.bboxes.count, 1)
        XCTAssertEqual(region.bboxes[0].originalDetectionId, regionDetectionId)
        XCTAssertEqual(tumor.bboxes.count, 1)
        XCTAssertEqual(tumor.bboxes[0].originalDetectionId, tumorDetectionId)
    }
}
