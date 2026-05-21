import XCTest
@testable import BrainScan

final class CoordinateConverterTests: XCTestCase {
    func test_physical_scales_by_dpi() {
        let logical = CGRect(x: 100, y: 200, width: 50, height: 60)
        let physical = CoordinateConverter.physical(logical, dpi: 2.0)
        XCTAssertEqual(physical, CGRect(x: 200, y: 400, width: 100, height: 120))
    }

    func test_physical_non_retina_unchanged() {
        let logical = CGRect(x: 10, y: 20, width: 30, height: 40)
        XCTAssertEqual(CoordinateConverter.physical(logical, dpi: 1.0), logical)
    }

    func test_tumor_in_crop_subtracts_region_origin_in_physical_space() {
        // Спека: ui_tumor {1620,1080,50,50}, region origin даёт смещение.
        let region = CGRect(x: 1600, y: 1000, width: 200, height: 200)
        let tumor = CGRect(x: 1620, y: 1080, width: 50, height: 50)
        let crop = CoordinateConverter.tumorInCrop(tumorLogical: tumor,
                                                   regionLogical: region, dpi: 2.0)
        // physical tumor origin (3240,2160) - physical region origin (3200,2000)
        XCTAssertEqual(crop, CGRect(x: 40, y: 160, width: 100, height: 100))
    }

    func test_tumor_in_crop_at_region_origin_is_zero() {
        let region = CGRect(x: 500, y: 500, width: 100, height: 100)
        let tumor = CGRect(x: 500, y: 500, width: 20, height: 20)
        let crop = CoordinateConverter.tumorInCrop(tumorLogical: tumor,
                                                   regionLogical: region, dpi: 2.0)
        XCTAssertEqual(crop.origin, CGPoint(x: 0, y: 0))
        XCTAssertEqual(crop.size, CGSize(width: 40, height: 40))
    }
}
